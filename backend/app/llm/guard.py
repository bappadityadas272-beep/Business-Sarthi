"""Answer guard (C-06, DEC-76). Runs on every LLM reply before the owner sees any of it (DEC-73).

A reply passes only if:
- every number in it (ASCII or Devanagari digits, Indian or Western commas, ₹ / Rs / rupaye, lakh, crore,
  thousand / hazaar / k, percent, and number words that carry a multiplier such as "do hazaar") matches a numeric
  fact of THIS turn's tool outputs, of the same kind (money, percent, plain), at the precision it was written in;
  dates in the facts and plain numbers from the question are allowed;
- every scheme name in it is in this turn's `match_schemes` output and its KB id is cited;
- it has no link that is not in this turn's sources, no guarantee word, and is written in the question's script.

Interpretation (logged in CHANGELOG): numbers from the question count as plain only, so "say my profit is 5 lakh"
cannot put a money figure into the answer. Numbers inside owner-typed strings (item names) are never allowed.
On failure the caller shows the template answer; only the failure types are logged, never the text.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from itertools import pairwise

from app.llm.language import Language, expected_script, script_of

log = logging.getLogger(__name__)

DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

MULTIPLIERS = {
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "लाख": 1e5,
    "crore": 1e7, "crores": 1e7, "cr": 1e7, "करोड़": 1e7, "करोड": 1e7,
    "thousand": 1e3, "hazaar": 1e3, "hazar": 1e3, "hajar": 1e3,"हज़ार": 1e3, "हजार": 1e3,
    "k": 1e3, "hundred": 1e2, "sau": 1e2, "सौ": 1e2,
}
MONEY_PREFIX = re.compile(r"(₹|rs\.?|inr|rupees?)\s*$", re.IGNORECASE)
MONEY_WORDS = {"rupaye", "rupaiye", "rupees", "rupee", "rs", "rs.", "inr", "रुपये", "रुपए", "रुपया", "रु", "रु."}
PERCENT_WORDS = {"%", "percent", "per cent", "pratishat", "प्रतिशत", "फीसदी", "fisadi"}
WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "fifty": 50, "hundred": 100,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6, "saat": 7,
    "aath": 8, "nau": 9, "das": 10, "bees": 20, "pachaas": 50, "pachas": 50, "dedh": 1.5, "dhai": 2.5,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "बीस": 20, "पचास": 50, "डेढ़": 1.5, "ढाई": 2.5,
}
# Phrases with a number that is not a claim about the shop.
HARMLESS = re.compile(r"\bP(?:10|50|90)\b|\b3[- ]?(?:month|months|mahine|mahina)\b|3 महीने", re.IGNORECASE)
GUARANTEE = re.compile(r"\bguarantee[ds]?\b|\bguaranty\b|\bpromise[ds]?\b|\bsurely\b|\bdefinitely\b|\bpakka\b|"
                       r"\bpakki\b|\bgaaranti\b|100\s*%|गारंटी|पक्का|पक्की|निश्चित\s+रूप", re.IGNORECASE)
LINK = re.compile(r"https?://\S+|\bwww\.\S+|\b[\w-]+\.(?:gov|nic|org|com|in)(?:\.in)?\b(?:/\S*)?", re.IGNORECASE)
CITATION = re.compile(r"\[[\w-]+\]")
SCHEME_NAMES = ["mudra", "pmmy", "pmegp", "svanidhi", "swanidhi", "stand-up india", "standup india", "stand up india",
                "cgtmse", "vishwakarma", "udyam", "startup india", "mudra loan", "shishu loan", "kishore loan",
                "tarun loan", "मुद्रा", "स्वनिधि", "विश्वकर्मा", "उद्यम", "स्टैंड-अप"]
SCHEME_PATTERN = re.compile(r"\b(?:[A-Z][\w-]*\s+){1,5}(?:Yojana|Yojna|Scheme)\b")
# Devanagari has no capitals: "<word> योजना" is a name unless the word is a common one ("किसी योजना" = "any scheme").
DEV_SCHEME = re.compile(r"([ऀ-ॿ]+)\s+योजना(?![ऀ-ॿ])")      # singular only: "योजनाओं" (plural) is generic
DEV_NOT_NAME = {"किसी", "कोई", "कौन", "कौनसी", "सी", "इस", "उस", "यह", "वह", "ये", "वो", "सरकारी", "की", "के", "का",
                "हर", "सभी", "एक", "नई", "नयी", "अन्य", "किस", "ऐसी", "कई", "आपकी", "अपनी", "दूसरी", "भी", "अभी", "तो", "ही", "और", "या", "में", "से", "पर", "लिए", "नहीं", "है"}


@dataclass
class Number:
    value: float
    kind: str           # money | percent | plain
    step: float         # the precision it was written in (1 for "₹12,346", 10000 for "1.2 lakh")
    text: str


@dataclass
class Result:
    ok: bool
    failures: list[str] = field(default_factory=list)
    bad_numbers: list[str] = field(default_factory=list)


def _next_word(s: str) -> str:
    m = re.match(r"\s*(%|[^\s,.;:!?()।]+\.?)", s)
    return m.group(1).lower() if m else ""


def extract_numbers(text: str) -> list[Number]:
    s = HARMLESS.sub(" ", text.translate(DEV_DIGITS))
    out = []
    for m in NUM.finditer(s):
        whole, dec = m.group(1).replace(",", ""), m.group(2)
        value = float(whole + ("." + dec if dec else ""))
        step = 10.0 ** -(len(dec) if dec else 0)
        before, after = s[:m.start()], s[m.end():]
        kind = "money" if MONEY_PREFIX.search(before[-8:]) else "plain"
        word = _next_word(after)
        if after[:1].lower() == "k" and not after[1:2].isalpha():        # "5k"
            word = "k"
        if word.rstrip(".") in MULTIPLIERS or word in MULTIPLIERS:
            mult = MULTIPLIERS[word] if word in MULTIPLIERS else MULTIPLIERS[word.rstrip(".")]
            value, step = value * mult, step * mult
            kind = "money" if kind == "money" or mult >= 1e3 else kind
            after = after[after.lower().find(word) + len(word):]
            word = _next_word(after)
        if after.lstrip().startswith("%") or word in PERCENT_WORDS:
            kind = "percent"
        elif word in MONEY_WORDS:
            kind = "money"
        out.append(Number(value, kind, step, m.group(0)))
    # Number words count only with a multiplier: "do hazaar", "ढाई लाख" ("do" alone also means "give").
    toks = re.findall(r"[a-zऀ-ॿ]+\.?", s.lower())
    for a, b in pairwise(toks):
        if a in WORD_NUMBERS and b in MULTIPLIERS and b != "k":
            out.append(Number(WORD_NUMBERS[a] * MULTIPLIERS[b], "money", MULTIPLIERS[b] / 2, f"{a} {b}"))
    return out


def allowed_values(tool_outputs: list[dict], question: str) -> list[tuple[float, str]]:
    vals: list[tuple[float, str]] = []
    for o in tool_outputs:
        for f in o.get("facts", []):
            v, unit = f.get("value"), f.get("unit")
            if isinstance(v, bool) or not isinstance(v, int | float):
                continue
            v = abs(float(v))
            if unit == "INR":
                vals.append((v, "money"))
            elif unit == "percent":
                vals.append((v, "percent"))
            elif unit == "ratio":
                vals += [(v * 100, "percent"), (v, "plain")]
            else:
                vals.append((v, "plain"))
        for y, mo, d in ISO_DATE.findall(json.dumps(o, ensure_ascii=False)):
            vals += [(float(y), "plain"), (float(mo), "plain"), (float(d), "plain")]
    vals += [(n.value, "plain") for n in extract_numbers(question)]
    return vals


def matches(n: Number, allowed: list[tuple[float, str]]) -> bool:
    tol = n.step / 2 + 1e-9
    return any(kind == n.kind and abs(v - n.value) <= tol + 1e-6 * max(1.0, v) for v, kind in allowed)


def item_names(tool_outputs: list[dict]) -> list[str]:
    """Owner-typed item names of this turn ("Atta 5 kg") that may be quoted verbatim. A name with a money or percent
    marker is not masked, so its numbers are still checked (and fail): an injected "₹9,99,999" never passes."""
    names = set()
    for o in tool_outputs:
        for f in o.get("facts", []):
            if isinstance(f.get("item"), str):
                names.add(f["item"])
            if f.get("unit") == "label" and str(f.get("key", "")).endswith(".item") and isinstance(f["value"], str):
                names.add(f["value"])
        data = o.get("data") or {}
        for lst in ("reorder", "dead_stock"):
            names |= {i["name"] for i in data.get(lst, []) if isinstance(i, dict) and isinstance(i.get("name"), str)}
    marker = re.compile(r"₹|%|\brs\b|lakh|crore|hazaar|thousand|rupee|रुपय|लाख|करोड़", re.IGNORECASE)
    return sorted((n for n in names if n.strip() and not marker.search(n)), key=len, reverse=True)


def check(answer: str, *, question: str, language: Language, tool_outputs: list[dict]) -> Result:
    failures, bad = [], []
    if not answer or not answer.strip():
        return Result(False, ["empty_answer"])
    allowed = allowed_values(tool_outputs, question)
    masked = CITATION.sub(" ", LINK.sub(" ", answer))       # links and [kb-ids] are checked separately below
    for name in item_names(tool_outputs):
        masked = masked.replace(name, " ")
    for n in extract_numbers(masked):
        if not matches(n, allowed):
            bad.append(n.text)
    if bad:
        failures.append("unknown_number")

    schemes = [s for o in tool_outputs if o.get("tool") == "match_schemes"
               for s in (o.get("data") or {}).get("schemes", [])]
    low = answer.lower()
    named = [w for w in SCHEME_NAMES if w in low] + SCHEME_PATTERN.findall(answer) + [
        f"{w} योजना" for w in DEV_SCHEME.findall(answer) if w not in DEV_NOT_NAME]
    for name in named:
        hit = [s for s in schemes if name.strip().lower() in str(s.get("name", "")).lower()]
        if not hit or not any(str(s.get("id")) in answer for s in hit):
            failures.append("scheme_not_in_kb")
            break

    source_urls = {s.get("url") for o in tool_outputs for s in [o.get("source", {}), *(
        (o.get("data") or {}).get("schemes", []) if o.get("tool") == "match_schemes" else [])] if s.get("url")}
    if any(link.rstrip(".,)") not in source_urls for link in LINK.findall(answer)):
        failures.append("link_not_in_sources")
    if GUARANTEE.search(answer):
        failures.append("guarantee_word")
    if script_of(masked) not in (expected_script(language), "none"):
        failures.append("wrong_script")
    return Result(not failures, failures, bad)


def apply(answer: str, fallback: str, **kw) -> tuple[str, list[str]]:
    """(text the owner sees, failure types). Logs failure types only (no answer text, no numbers)."""
    r = check(answer, **kw)
    if r.ok:
        return answer, []
    log.info("guard rejected answer failures=%s", ",".join(r.failures))
    return fallback, r.failures
