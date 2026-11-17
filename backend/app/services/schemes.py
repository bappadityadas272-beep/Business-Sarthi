"""Scheme matcher (C-03, ML7, ML_PLAN section 9, DEC-86, DEC-87). The code decides; nothing here is advice.

1. Hard eligibility checks per field: pass, fail or unknown. One fail removes the scheme.
   - sector: from the shop type (a kirana shop is retail/trading)
   - investment: the shop's budget against min_investment / max_investment
   - age, category, state: from the request only, never stored (DEC-86); not given = unknown
2. Rank what is left by embedding similarity between the question (or the shop type) and the scheme text,
   then by fewer unknown checks, then by id.
3. Each result: why it may fit, what is missing or must be confirmed, the source URL, `last_verified`,
   an `unverified` label when `verified` is false, and the "check the official page" notice.

Scheme facts come only from the KB file (AGENTS rule 3). A missing or invalid KB gives no schemes.
"""
from __future__ import annotations

import logging
from datetime import date

from app.llm.templates import inr
from app.models import Shop
from app.rag import index as ixmod
from app.rag import kb as kbmod

log = logging.getLogger("sarthi.schemes")
LANGS = ("hi", "hinglish", "en")
TOP_K = 3

TEXT = {
    "en": {
        "fit.sector": "it covers {sector} businesses like your shop",
        "fit.sector_any": "it is open to any sector",
        "fit.investment": "your planned investment of {budget} is within its limit",
        "fit.age": "your age is within its range",
        "fit.category": "it is for the {category} category you gave",
        "fit.state": "it covers {state}",
        "fit.all_india": "it covers all of India",
        "miss.age": "your age (it needs {range})",
        "miss.category": "whether you are in one of these categories: {cats}",
        "miss.state": "your state (it covers only {states})",
        "unverified": "Not yet checked by our team against the official page.",
        "notice": "This is guidance from a prototype, not financial advice. Rules change: check the official page "
                  "before you apply.",
    },
    "hinglish": {
        "fit.sector": "yeh aapki dukaan jaise {sector} business ke liye hai",
        "fit.sector_any": "yeh har sector ke liye khula hai",
        "fit.investment": "aapka planned investment {budget} iski limit ke andar hai",
        "fit.age": "aapki umar iski range mein hai",
        "fit.category": "yeh aapki batayi {category} category ke liye hai",
        "fit.state": "yeh {state} mein laagu hai",
        "fit.all_india": "yeh poore Bharat mein laagu hai",
        "miss.age": "aapki umar (ise {range} chahiye)",
        "miss.category": "kya aap in categories mein se kisi mein hain: {cats}",
        "miss.state": "aapka rajya (yeh sirf {states} mein hai)",
        "unverified": "Hamari team ne ise abhi official page se check nahi kiya hai.",
        "notice": "Yeh ek prototype ki jaankari hai, financial salah nahi. Niyam badalte rehte hain: apply karne se "
                  "pehle official page zaroor dekhiye.",
    },
    "hi": {
        "fit.sector": "यह आपकी दुकान जैसे {sector} व्यवसाय के लिए है",
        "fit.sector_any": "यह हर क्षेत्र के लिए खुला है",
        "fit.investment": "आपका नियोजित निवेश {budget} इसकी सीमा के भीतर है",
        "fit.age": "आपकी उम्र इसकी सीमा में है",
        "fit.category": "यह आपकी बताई {category} श्रेणी के लिए है",
        "fit.state": "यह {state} में लागू है",
        "fit.all_india": "यह पूरे भारत में लागू है",
        "miss.age": "आपकी उम्र (इसके लिए {range} चाहिए)",
        "miss.category": "क्या आप इनमें से किसी श्रेणी में हैं: {cats}",
        "miss.state": "आपका राज्य (यह केवल {states} में है)",
        "unverified": "हमारी टीम ने इसे अभी आधिकारिक पेज से नहीं जाँचा है।",
        "notice": "यह एक प्रोटोटाइप की जानकारी है, वित्तीय सलाह नहीं। नियम बदलते रहते हैं: आवेदन से पहले "
                  "आधिकारिक पेज ज़रूर देखिए।",
    },
}


def _age_range(e: kbmod.Eligibility) -> str:
    if e.age_min is not None and e.age_max is not None:
        return f"{e.age_min}-{e.age_max}"
    return f"{e.age_min}+" if e.age_min is not None else f"<= {e.age_max}"


def check(s: kbmod.Scheme, shop: Shop, profile: dict) -> dict:
    """{field: (status, reason_key, params)} with status pass | fail | unknown. Only restricting rules count."""
    e = s.eligibility
    out: dict[str, tuple[str, str | None, dict]] = {}
    sectors = kbmod.SHOP_TYPE_SECTORS.get(shop.shop_type)
    if e.sectors is None:
        out["sector"] = ("pass", "fit.sector_any", {})
    elif sectors is None:
        out["sector"] = ("unknown", None, {})
    else:
        both = sorted(sectors & set(e.sectors))
        out["sector"] = ("pass", "fit.sector", {"sector": "/".join(both)}) if both else ("fail", None, {})
    if e.min_investment is not None or e.max_investment is not None:
        ok = (e.min_investment is None or shop.budget >= e.min_investment) and \
             (e.max_investment is None or shop.budget <= e.max_investment)
        out["investment"] = ("pass", "fit.investment", {"budget": inr(shop.budget)}) if ok else ("fail", None, {})
    if e.age_min is not None or e.age_max is not None:
        age = profile.get("age")
        if age is None:
            out["age"] = ("unknown", "miss.age", {"range": _age_range(e)})
        else:
            ok = (e.age_min is None or age >= e.age_min) and (e.age_max is None or age <= e.age_max)
            out["age"] = ("pass", "fit.age", {}) if ok else ("fail", None, {})
    if e.categories is not None:
        cats = set(profile.get("categories") or [])
        if not cats:
            out["category"] = ("unknown", "miss.category", {"cats": ", ".join(e.categories)})
        else:
            both = sorted(cats & set(e.categories))
            out["category"] = ("pass", "fit.category", {"category": ", ".join(both)}) if both else ("fail", None, {})
    if e.states is None:
        out["state"] = ("pass", "fit.all_india", {})
    else:
        state = (profile.get("state") or "").strip().casefold()
        if not state:
            out["state"] = ("unknown", "miss.state", {"states": ", ".join(e.states)})
        elif state in {x.casefold() for x in e.states}:
            out["state"] = ("pass", "fit.state", {"state": profile["state"].strip()})
        else:
            out["state"] = ("fail", None, {})
    return out


def query_text(shop: Shop, need: str | None) -> str:
    return need.strip() if need and need.strip() else f"{shop.shop_type} shop"


def match(shop: Shop, today: date, profile: dict | None = None, language: str = "en", k: int = TOP_K,
          ix: ixmod.Index | None = None) -> dict:
    profile = {key: v for key, v in (profile or {}).items() if v not in (None, "", [])}
    lang = language if language in LANGS else "en"
    tx = TEXT[lang]
    base = {"shop_id": shop.id, "as_of": today.isoformat(), "language": lang, "profile_used": profile,
            "profile_stored": False, "notice": tx["notice"], "schemes": [], "excluded": []}
    try:
        ix = ix or ixmod.current()
    except kbmod.KBMissing:
        return {**base, "note": "no_verified_source", "kb": None}
    except kbmod.KBInvalid as e:
        log.warning("scheme KB is invalid (%d problems); run make kb-check", len(e.errors))
        return {**base, "note": "kb_invalid", "kb": None}
    sim = ix.similarity(query_text(shop, profile.get("need")))
    rows, excluded = [], []
    for s in ix.kb.schemes:
        checks = check(s, shop, profile)
        failed = sorted(f for f, (st, _, _) in checks.items() if st == "fail")
        if failed:
            excluded.append({"id": s.id, "failed": failed})
            continue
        unknown = [c for c in checks.values() if c[0] == "unknown"]
        rows.append((s, checks, len(unknown)))
    rows.sort(key=lambda r: (-sim.get(r[0].id, 0.0), r[2], r[0].id))
    out = []
    for s, checks, n_unknown in rows[:k]:
        fit = [tx[key].format(**p) for st, key, p in checks.values() if st == "pass" and key]
        missing = [tx[key].format(**p) for st, key, p in checks.values() if st == "unknown" and key]
        if any(st == "unknown" and not key for st, key, _ in checks.values()):
            missing.append({"en": "whether your type of business is covered", "hinglish":
                            "kya aapka business type isme aata hai", "hi": "क्या आपका व्यवसाय इसमें आता है"}[lang])
        out.append({
            "id": s.id, "name": s.name_hi if lang == "hi" and s.name_hi else s.name, "name_en": s.name,
            "type": s.type,
            "summary": s.benefit_summary_hi if lang == "hi" and s.benefit_summary_hi else s.benefit_summary,
            "how_to_apply": s.how_to_apply,
            "why_it_may_fit": fit, "missing_requirements": missing,
            "please_confirm": list(s.eligibility.other_requirements),
            "checks": {f: st for f, (st, _, _) in checks.items()}, "unknown_checks": n_unknown,
            "similarity": sim.get(s.id, 0.0),
            "source_url": str(s.source_url), "url": str(s.source_url), "last_verified": s.last_verified.isoformat(),
            "verified": s.verified, "label": None if s.verified else "unverified",
            "label_text": None if s.verified else tx["unverified"],
        })
    return {**base, "schemes": out, "excluded": excluded, "note": None if out else "no_match",
            "kb": {"version": ix.kb.version, "entries": len(ix.kb.schemes), "test_only": ix.kb.test_only,
                   "embedder": ix.embedder.name, "index": ix.source,
                   "embedder_is_fallback": ix.embedder.name.startswith("fallback")}}
