"""Template answers (C-05). Used for smalltalk, refusals, out-of-scope and schemes without a KB (no LLM call, DEC-77),
by the stub provider, and as the guard's fallback (C-06). Every number comes from a tool output; none is computed
here beyond rounding for display.
"""
from datetime import date

HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर",
             "दिसंबर"]
EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def indian_digits(n: int) -> str:
    """12345678 -> 1,23,45,678 (Indian grouping)."""
    s = str(abs(n))
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head, *groups]) + "," + tail
    return ("-" if n < 0 else "") + s


def inr(v: float) -> str:
    return "₹" + indian_digits(round(v))


def num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def pct(ratio_or_percent: float, is_ratio: bool = True) -> str:
    v = ratio_or_percent * 100 if is_ratio else ratio_or_percent
    return f"{num(round(v, 1))}%"


def day(iso: str, lang: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {(HI_MONTHS if lang == 'hi' else EN_MONTHS)[d.month - 1]}"


T = {
    "en": {
        "period.this_month": "This month", "period.last_month": "Last month",
        "period.last_30_days": "Last 30 days", "period.last_90_days": "Last 90 days",
        "profit": "{period} ({start} to {end}): sales {s}, purchases {p}, expenses {e}.",
        "profit.plus": "Profit before EMI: {x}.", "profit.minus": "Loss before EMI: {x}.",
        "profit.emi": "Your loan EMI is {m} a month; it is not taken off above.",
        "profit.partial": "Based on {n} logged days out of {d}.",
        "profit.empty": "Nothing is logged for this period yet.",
        "profit.nologs": "No sales were logged from {start} to {end}.",
        "forecast": "Forecast for {start} to {end}: sales between {p10} and {p90}, most likely {p50}. This is an estimate.",
        "forecast.none": "There is no forecast for your shop yet.",
        "review": "Latest review ({start} to {end}): {decision}. Confidence: {confidence}.",
        "review.profit": "Profit per month in that period: {x}.",
        "review.none": "Your first review is not ready yet.",
        "decision.grow": "grow", "decision.hold": "hold", "decision.pivot": "pivot (change something)",
        "confidence.low": "low", "confidence.medium": "medium",
        "stock.reorder": "Order now: {items}.", "stock.noreorder": "No item needs ordering right now.",
        "stock.dead": "Not selling: {items}, worth {v} in total.",
        "stock.none": "You have no stock records yet.",
        "alerts.none": "You have no open alerts.", "alerts.head": "Open alerts:",
        "alert.sales_dip": "sales dip, sales down {drop}%", "alert.low_stock": "low stock",
        "alert.dead_stock": "unsold stock worth {value}", "alert.emi_due": "EMI {emi} due on {due}",
        "alert.data_gap": "no log for {days} days", "alert.other": "{kind}",
        "alert.cleared": " (no longer active)",
        "schemes.none": "I do not have verified scheme information yet, so I cannot name a scheme. Please check the official government page or ask your bank.",
        "smalltalk": "Namaste! I am Business Sarthi. Ask me about your sales, profit, stock, alerts or how to use the app.",
        "out_of_scope": "Sorry, I can only help with your shop's numbers, stock, alerts and the app.",
        "refusal.medical": "Sorry, I cannot help with health questions. Please see a doctor.",
        "refusal.legal": "Sorry, I cannot give legal advice. Please talk to a lawyer.",
        "refusal.guarantee": "Sorry, no one can promise a sure result, and I do not give investment advice. I can show your own numbers and estimates.",
        "unknown": "Sorry, I do not know that.",
    },
    "hinglish": {
        "period.this_month": "Is mahine", "period.last_month": "Pichhle mahine",
        "period.last_30_days": "Pichhle 30 din", "period.last_90_days": "Pichhle 90 din",
        "profit": "{period} ({start} se {end}): bikri {s}, kharid {p}, kharcha {e}.",
        "profit.plus": "EMI se pehle munafa: {x}.", "profit.minus": "EMI se pehle ghata: {x}.",
        "profit.emi": "Aapki loan EMI {m} mahina hai; yeh upar nahi ghatayi gayi hai.",
        "profit.partial": "Yeh {d} mein se {n} din ke hisaab par hai.",
        "profit.empty": "Is samay ka abhi kuch darj nahi hai.",
        "profit.nologs": "{start} se {end} tak koi bikri darj nahi hai.",
        "forecast": "{start} se {end} ka anumaan: bikri {p10} se {p90} ke beech, sabse sambhav {p50}. Yeh sirf anumaan hai.",
        "forecast.none": "Aapki dukaan ka abhi koi anumaan nahi bana hai.",
        "review": "Pichhli samiksha ({start} se {end}): {decision}. Bharosa: {confidence}.",
        "review.profit": "Us samay mahine ka munafa: {x}.",
        "review.none": "Aapki pehli samiksha abhi taiyaar nahi hai.",
        "decision.grow": "grow (badhaiye)", "decision.hold": "hold (abhi ruke rahiye)",
        "decision.pivot": "pivot (kuch badlaav kijiye)",
        "confidence.low": "kam", "confidence.medium": "theek-thaak",
        "stock.reorder": "Abhi mangwaiye: {items}.", "stock.noreorder": "Abhi kuch mangwane ki zaroorat nahi hai.",
        "stock.dead": "Nahi bik raha: {items}, kul {v} ka.",
        "stock.none": "Aapka abhi koi stock record nahi hai.",
        "alerts.none": "Aapka koi khula alert nahi hai.", "alerts.head": "Khule alerts:",
        "alert.sales_dip": "bikri girawat, bikri {drop}% kam", "alert.low_stock": "stock kam",
        "alert.dead_stock": "na bikne wala maal {value} ka", "alert.emi_due": "EMI {emi} {due} ko deni hai",
        "alert.data_gap": "{days} din se hisaab nahi likha", "alert.other": "{kind}",
        "alert.cleared": " (ab active nahi)",
        "schemes.none": "Mere paas abhi yojanaon ki sahi (verified) jaankari nahi hai, isliye main kisi yojana ka naam nahi bataunga. Kripya sarkari official page dekhiye ya apne bank se poochhiye.",
        "smalltalk": "Namaste! Main Business Sarthi hoon. Mujhse apni bikri, munafa, stock, alerts ya app ke baare mein poochhiye.",
        "out_of_scope": "Maaf kijiye, main sirf aapki dukaan ke hisaab, stock, alerts aur app mein madad kar sakta hoon.",
        "refusal.medical": "Maaf kijiye, main sehat ke sawaalon mein madad nahi kar sakta. Kripya doctor se miliye.",
        "refusal.legal": "Maaf kijiye, main kanooni salah nahi de sakta. Kripya vakil se baat kijiye.",
        "refusal.guarantee": "Maaf kijiye, koi bhi pakka nateeja nahi bata sakta, aur main nivesh ki salah nahi deta. Main aapke apne aankde aur anumaan dikha sakta hoon.",
        "unknown": "Maaf kijiye, mujhe yeh nahi pata.",
    },
    "hi": {
        "period.this_month": "इस महीने", "period.last_month": "पिछले महीने",
        "period.last_30_days": "पिछले 30 दिन", "period.last_90_days": "पिछले 90 दिन",
        "profit": "{period} ({start} से {end}): बिक्री {s}, खरीद {p}, खर्च {e}।",
        "profit.plus": "किस्त से पहले मुनाफा: {x}।", "profit.minus": "किस्त से पहले घाटा: {x}।",
        "profit.emi": "आपके लोन की किस्त {m} महीना है; यह ऊपर नहीं घटाई गई है।",
        "profit.partial": "यह {d} में से {n} दिन के हिसाब पर है।",
        "profit.empty": "इस समय का अभी कुछ दर्ज नहीं है।",
        "profit.nologs": "{start} से {end} तक कोई बिक्री दर्ज नहीं है।",
        "forecast": "{start} से {end} का अनुमान: बिक्री {p10} से {p90} के बीच, सबसे संभव {p50}। यह सिर्फ़ अनुमान है।",
        "forecast.none": "आपकी दुकान का अभी कोई अनुमान नहीं बना है।",
        "review": "पिछली समीक्षा ({start} से {end}): {decision}। भरोसा: {confidence}।",
        "review.profit": "उस समय महीने का मुनाफा: {x}।",
        "review.none": "आपकी पहली समीक्षा अभी तैयार नहीं है।",
        "decision.grow": "बढ़ाइए (grow)", "decision.hold": "अभी रुके रहिए (hold)",
        "decision.pivot": "कुछ बदलाव कीजिए (pivot)",
        "confidence.low": "कम", "confidence.medium": "ठीक-ठाक",
        "stock.reorder": "अभी मँगवाइए: {items}।", "stock.noreorder": "अभी कुछ मँगवाने की ज़रूरत नहीं है।",
        "stock.dead": "नहीं बिक रहा: {items}, कुल {v} का।",
        "stock.none": "आपका अभी कोई स्टॉक रिकॉर्ड नहीं है।",
        "alerts.none": "आपका कोई खुला अलर्ट नहीं है।", "alerts.head": "खुले अलर्ट:",
        "alert.sales_dip": "बिक्री में गिरावट, बिक्री {drop}% कम", "alert.low_stock": "स्टॉक कम",
        "alert.dead_stock": "न बिकने वाला माल {value} का", "alert.emi_due": "किस्त {emi} {due} को देनी है",
        "alert.data_gap": "{days} दिन से हिसाब नहीं लिखा", "alert.other": "{kind}",
        "alert.cleared": " (अब सक्रिय नहीं)",
        "schemes.none": "मेरे पास अभी योजनाओं की सही (सत्यापित) जानकारी नहीं है, इसलिए मैं किसी योजना का नाम नहीं बताऊँगा। कृपया सरकारी आधिकारिक पेज देखिए या अपने बैंक से पूछिए।",
        "smalltalk": "नमस्ते! मैं बिज़नेस सारथी हूँ। मुझसे अपनी बिक्री, मुनाफा, स्टॉक, अलर्ट या ऐप के बारे में पूछिए।",
        "out_of_scope": "माफ़ कीजिए, मैं सिर्फ़ आपकी दुकान के हिसाब, स्टॉक, अलर्ट और ऐप में मदद कर सकता हूँ।",
        "refusal.medical": "माफ़ कीजिए, मैं सेहत के सवालों में मदद नहीं कर सकता। कृपया डॉक्टर से मिलिए।",
        "refusal.legal": "माफ़ कीजिए, मैं कानूनी सलाह नहीं दे सकता। कृपया वकील से बात कीजिए।",
        "refusal.guarantee": "माफ़ कीजिए, कोई भी पक्का नतीजा नहीं बता सकता, और मैं निवेश की सलाह नहीं देता। मैं आपके अपने आँकड़े और अनुमान दिखा सकता हूँ।",
        "unknown": "माफ़ कीजिए, मुझे यह नहीं पता।",
    },
}


def t(lang: str, key: str, **kw) -> str:
    return T[lang][key].format(**kw)


def _profit(o: dict, lang: str) -> list[str]:
    d = o["data"]
    if o["note"] == "period_empty":
        return [t(lang, "profit.empty")]
    start, end = day(d["start"], lang), day(d["end"], lang)
    if o["note"] == "no_logs_in_period":
        return [t(lang, "profit.nologs", start=start, end=end)]
    x = d["operating_profit"]
    out = [t(lang, "profit", period=t(lang, f"period.{d['period']}"), start=start, end=end, s=inr(d["sales"]),
             p=inr(d["purchases"]), e=inr(d["expenses"])),
           t(lang, "profit.plus" if x >= 0 else "profit.minus", x=inr(abs(x)))]
    if d.get("monthly_emi"):
        out.append(t(lang, "profit.emi", m=inr(d["monthly_emi"])))
    if d["days_logged"] < d["days_in_period"]:
        out.append(t(lang, "profit.partial", n=d["days_logged"], d=d["days_in_period"]))
    return out


def _forecast(o: dict, lang: str) -> list[str]:
    d = o["data"]
    if not d:
        return [t(lang, "forecast.none")]
    m = next((m for m in d["months"] if m["k"] == d["current_month"]), d["months"][0])
    return [t(lang, "forecast", start=day(m["start"], lang), end=day(m["end"], lang), p10=inr(m["p10"]),
              p50=inr(m["p50"]), p90=inr(m["p90"]))]


def _review(o: dict, lang: str) -> list[str]:
    d = o["data"]
    if not d:
        return [t(lang, "review.none")]
    out = [t(lang, "review", start=day(d["period_start"], lang), end=day(d["period_end"], lang),
             decision=t(lang, f"decision.{d['decision']}"), confidence=t(lang, f"confidence.{d['confidence']}"))]
    profit = next((f["value"] for f in o["facts"] if f["key"] == "operating_profit_per_month"), None)
    if profit is not None:
        out.append(t(lang, "review.profit", x=(inr(profit) if profit >= 0 else "-" + inr(-profit))))
    return out


def _stock(o: dict, lang: str) -> list[str]:
    d = o["data"]
    if not d:
        return [t(lang, "stock.none")]
    out = []
    if d["reorder"]:
        items = ", ".join(f"{i['name']} ({num(i['reorder_qty'])} {i['unit']})" if i["reorder_qty"] else i["name"]
                          for i in d["reorder"])
        out.append(t(lang, "stock.reorder", items=items))
    else:
        out.append(t(lang, "stock.noreorder"))
    if d["dead_stock"]:
        out.append(t(lang, "stock.dead", items=", ".join(i["name"] for i in d["dead_stock"]),
                     v=inr(d["dead_stock_value"])))
    return out


def _alerts(o: dict, lang: str) -> list[str]:
    alerts = o["data"]["alerts"]
    if not alerts:
        return [t(lang, "alerts.none")]
    facts = {(f.get("alert_id"), f["key"].split(".")[-1]): f["value"] for f in o["facts"]}
    parts = []
    for a in alerts:
        p = lambda k, a=a: facts.get((a["id"], k))
        kind = a["kind"]
        if kind == "sales_dip" and p("drop_percent") is not None:
            text = t(lang, "alert.sales_dip", drop=num(p("drop_percent")))
        elif kind == "dead_stock" and p("value") is not None:
            text = t(lang, "alert.dead_stock", value=inr(p("value")))
        elif kind == "emi_due" and p("emi") is not None:
            text = t(lang, "alert.emi_due", emi=inr(p("emi")), due=day(p("due_date"), lang))
        elif kind == "data_gap" and p("days_without_log") is not None:
            text = t(lang, "alert.data_gap", days=p("days_without_log"))
        elif kind == "low_stock":
            text = t(lang, "alert.low_stock")
        else:
            text = t(lang, "alert.other", kind=kind.replace("_", " "))
        parts.append(text + ("" if a["still_active"] else t(lang, "alert.cleared")))
    end = "।" if lang == "hi" else "."
    return [t(lang, "alerts.head") + " " + "; ".join(parts) + end]


RENDER = {"get_profit_summary": _profit, "get_forecast": _forecast, "get_latest_review": _review,
          "get_stock_advice": _stock, "get_alerts": _alerts}


def render(intent: str, tools: list[dict], language: str, refusal: str | None = None) -> str:
    lang = language if language in T else "en"
    if refusal:
        return t(lang, f"refusal.{refusal}")
    if intent == "smalltalk":
        return t(lang, "smalltalk")
    if intent == "schemes":
        return t(lang, "schemes.none")              # DEC-74: no KB yet, so never a scheme name
    if intent == "how_to":
        helps = [o for o in tools if o["tool"] == "app_help"]
        return helps[0]["data"]["text"][lang] if helps else t(lang, "unknown")
    if intent == "my_numbers":
        lines = [line for o in tools if o["tool"] in RENDER for line in RENDER[o["tool"]](o, lang)]
        return " ".join(lines) if lines else t(lang, "unknown")
    return t(lang, "out_of_scope")
