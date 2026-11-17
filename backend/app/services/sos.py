"""SOS (B-10, DEC-83): a shareable summary plus a guided checklist. Computed on request; nothing is stored.

Every number comes from the owner's logs, loans and alerts through the same code the chat tools use. The steps
are picked by fixed rules below (no LLM). No helpline or phone numbers are given: none are verified (DEC-83).
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm import templates as tpl
from app.llm import tools
from app.models import Loan, Shop
from app.services import loans as loan_dates

EMI_SOON_DAYS = 7           # an EMI due within a week is urgent enough to talk to the lender (assumption, DEC-83)
FEW_LOGS_SHARE = 2 / 3      # fewer logged days than this share of the 30: the summary is incomplete (assumption)
LANGS = ("hi", "hinglish", "en")

TEXT = {
    "en": {
        "head": "Business Sarthi SOS summary for {shop} (as of {asof}).",
        "emi": "Loan EMI {emi}: next due {due}, {left} instalments left.",
        "emi.none": "No loan recorded.", "emi.nodates": "Loan EMI {emi} a month (no start date recorded).",
        "steps": "What to do now:",
        "step.emi_soon": "Talk to your lender before {due}. Ask what options there are if you cannot pay in full.",
        "step.loss": "The last 30 days were a loss of {x}. Write down every expense and stop the ones that can wait.",
        "step.sales_dip": "Sales are down. Check what changed: items out of stock, a new shop nearby, fewer customers"
                          " on some days.",
        "step.low_stock": "Restock the items that sell fast first, before other purchases.",
        "step.dead_stock": "Stock worth {value} is not selling. Offer a discount or ask the supplier to take it"
                           " back.",
        "step.few_logs": "Only {n} of the last {d} days are logged. Log sales every day so this summary is complete.",
        "step.no_urgent": "No urgent problem was found in your logged numbers.",
        "step.share": "Share this summary with someone you trust, or show it at your bank.",
        "step.official": "For loans and schemes, check the official page. This is guidance from a prototype, not"
                         " financial advice.",
    },
    "hinglish": {
        "head": "Business Sarthi SOS summary: {shop} ({asof} tak).",
        "emi": "Loan EMI {emi}: agli kisht {due} ko, {left} kisht baaki.",
        "emi.none": "Koi loan darj nahi hai.", "emi.nodates": "Loan EMI {emi} mahina (shuru ki tareekh darj nahi).",
        "steps": "Ab kya karein:",
        "step.emi_soon": "{due} se pehle apne lender se baat karein. Poora na de paayein to kya vikalp hain, poochhein.",
        "step.loss": "Pichhle 30 din mein {x} ka nuksaan hua. Har kharcha likhein aur jo ruk sakte hain unhe rokein.",
        "step.sales_dip": "Bikri kam hui hai. Dekhein kya badla: maal khatam, paas mein nayi dukaan, ya kuch dinon"
                          " mein kam graahak.",
        "step.low_stock": "Pehle tezi se bikne wala maal bharein, baaki khareed baad mein.",
        "step.dead_stock": "{value} ka maal nahi bik raha. Chhoot dein ya supplier se waapas lene ko kahein.",
        "step.few_logs": "Pichhle {d} mein se sirf {n} din darj hain. Roz bikri likhein taaki summary poori ho.",
        "step.no_urgent": "Aapke darj aankdon mein koi zaroori samasya nahi mili.",
        "step.share": "Yeh summary kisi bharosemand vyakti ko dikhayein, ya bank mein dikhayein.",
        "step.official": "Loan aur yojana ke liye official page zaroor dekhein. Yeh prototype ki salaah hai, vittiya"
                         " salaah nahi.",
    },
    "hi": {
        "head": "बिज़नेस सारथी SOS सारांश: {shop} ({asof} तक)।",
        "emi": "लोन किस्त {emi}: अगली किस्त {due} को, {left} किस्तें बाकी।",
        "emi.none": "कोई लोन दर्ज नहीं है।", "emi.nodates": "लोन किस्त {emi} महीना (शुरू की तारीख दर्ज नहीं)।",
        "steps": "अब क्या करें:",
        "step.emi_soon": "{due} से पहले अपने लोन देने वाले से बात करें। पूरी किस्त न दे पाएँ तो क्या विकल्प हैं, पूछें।",
        "step.loss": "पिछले 30 दिनों में {x} का नुकसान हुआ। हर खर्च लिखें और जो रुक सकते हैं उन्हें रोकें।",
        "step.sales_dip": "बिक्री कम हुई है। देखें क्या बदला: माल खत्म, पास में नई दुकान, या कुछ दिनों में कम ग्राहक।",
        "step.low_stock": "पहले जल्दी बिकने वाला माल भरें, बाकी खरीद बाद में।",
        "step.dead_stock": "{value} का माल नहीं बिक रहा। छूट दें या सप्लायर से वापस लेने को कहें।",
        "step.few_logs": "पिछले {d} में से सिर्फ़ {n} दिन दर्ज हैं। रोज़ बिक्री लिखें ताकि सारांश पूरा हो।",
        "step.no_urgent": "आपके दर्ज आँकड़ों में कोई ज़रूरी समस्या नहीं मिली।",
        "step.share": "यह सारांश किसी भरोसेमंद व्यक्ति को दिखाएँ, या बैंक में दिखाएँ।",
        "step.official": "लोन और योजना के लिए आधिकारिक पेज ज़रूर देखें। यह प्रोटोटाइप की सलाह है, वित्तीय सलाह नहीं।",
    },
}


def _t(lang: str, key: str, **kw) -> str:
    return TEXT[lang][key].format(**kw)


def emi_status(db: Session, shop: Shop, today: date) -> list[dict]:
    out = []
    for ln in db.scalars(select(Loan).where(Loan.shop_id == shop.id).order_by(Loan.id)):
        st = loan_dates.status(ln.start_date, ln.due_day, ln.tenure_months, ln.emi, today)
        out.append({"loan_id": ln.id, "emi": ln.emi, "due_day": ln.due_day, "next_due_date": st["next_due_date"],
                    "days_to_next_due": st["days_to_next_due"], "instalments_left": st["instalments_left"]})
    return out


def steps_for(alerts: list[dict], alert_facts: dict, emi: list[dict], profit: dict) -> list[dict]:
    """The checklist, most urgent first. Each step is {key, params}; the params are numbers already shown above."""
    kinds = {a["kind"] for a in alerts if a["still_active"]}
    steps = []
    soon = [e for e in emi if e["days_to_next_due"] is not None and e["days_to_next_due"] <= EMI_SOON_DAYS]
    if soon or "emi_due" in kinds:
        nxt = min((e["next_due_date"] for e in soon), default=None)
        steps.append({"key": "emi_soon", "params": {"due_date": nxt.isoformat() if nxt else None}})
    if profit.get("days_logged") and profit["operating_profit"] < 0:
        steps.append({"key": "loss", "params": {"loss": round(-profit["operating_profit"], 2)}})
    for kind in ("sales_dip", "low_stock", "dead_stock"):
        if kind in kinds:
            params = {"value": alert_facts[kind]} if kind == "dead_stock" and kind in alert_facts else {}
            steps.append({"key": kind, "params": params})
    d_in = profit.get("days_in_period") or 0
    if d_in and profit.get("days_logged", 0) < FEW_LOGS_SHARE * d_in:
        steps.append({"key": "few_logs", "params": {"days_logged": profit.get("days_logged", 0), "days": d_in}})
    if not steps:
        steps.append({"key": "no_urgent", "params": {}})
    steps += [{"key": "share", "params": {}}, {"key": "official", "params": {}}]
    return steps


def _step_text(s: dict, lang: str) -> str:
    p, k = s["params"], s["key"]
    if k == "emi_soon":
        due = tpl.day(p["due_date"], tpl_lang(lang)) if p["due_date"] else "—"
        return _t(lang, "step.emi_soon", due=due)
    if k == "loss":
        return _t(lang, "step.loss", x=tpl.inr(p["loss"]))
    if k == "dead_stock":
        return _t(lang, "step.dead_stock", value=tpl.inr(p["value"])) if "value" in p else \
            _t(lang, "step.dead_stock", value="—")
    if k == "few_logs":
        return _t(lang, "step.few_logs", n=p["days_logged"], d=p["days"])
    return _t(lang, f"step.{k}")


def tpl_lang(lang: str) -> str:
    return "hi" if lang == "hi" else "en"          # month names: Devanagari for Hindi, English otherwise


def build(db: Session, shop: Shop, today: date, lang: str) -> dict:
    al = tools.get_alerts(db, shop, today)
    pr = tools.get_profit_summary(db, shop, today, "last_30_days")
    emi = emi_status(db, shop, today)
    profit = pr["data"]
    alert_facts = {f["key"].split(".")[1]: f["value"] for f in al["facts"] if f["key"].endswith(".value")}
    steps = steps_for(al["data"]["alerts"], alert_facts, emi, profit)

    lines = [_t(lang, "head", shop=shop.name or f"#{shop.id}", asof=tpl.day(today.isoformat(), tpl_lang(lang)))]
    lines += tpl.RENDER["get_alerts"](al, lang)
    lines += tpl.RENDER["get_profit_summary"](pr, lang)
    if not emi:
        lines.append(_t(lang, "emi.none"))
    for e in emi:
        if e["next_due_date"] is None:
            lines.append(_t(lang, "emi.nodates", emi=tpl.inr(e["emi"])))
        else:
            lines.append(_t(lang, "emi", emi=tpl.inr(e["emi"]), due=tpl.day(e["next_due_date"].isoformat(),
                                                                          tpl_lang(lang)), left=e["instalments_left"]))
    lines.append(_t(lang, "steps"))
    lines += [f"{i}. {_step_text(s, lang)}" for i, s in enumerate(steps, 1)]

    return {"shop_id": shop.id, "as_of": today, "language": lang, "stored": False,
            "alerts": al["data"]["alerts"], "emi": emi,
            "last_30_days": {k: profit.get(k) for k in ("start", "end", "sales", "purchases", "expenses",
                                                         "operating_profit", "days_logged", "days_in_period")},
            "steps": steps, "share_text": "\n".join(lines),
            "sources": [al["source"]["label"], pr["source"]["label"]]}
