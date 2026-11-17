"""Intent router (C-05): keyword rules in Hindi, Hinglish and English first; the LLM only classifies a message no
rule matched, and its answer must be one of the five labels (anything else = out_of_scope).

Intents: my_numbers | schemes | how_to | smalltalk | out_of_scope. A refusal (medical, legal, guaranteed returns or
investment advice) is checked before anything else and gives intent out_of_scope with `refusal` set.
"""
import logging
from dataclasses import dataclass, field

from app.llm.client import LLMClient, LLMError
from app.llm.language import tokens

log = logging.getLogger(__name__)

INTENTS: tuple[str, ...] = ("my_numbers", "schemes", "how_to", "smalltalk", "out_of_scope")
REFUSALS: tuple[str, ...] = ("medical", "legal", "guarantee")

# A keyword is a single word, a phrase (matched on whole words) or, in Devanagari, a substring (matras and
# postpositions attach to words in many ways).
REFUSAL_WORDS = {
    "medical": ["doctor", "medicine", "medicines", "tablet", "fever", "illness", "disease", "sick", "pregnant",
                "dawai", "dawa", "davai", "bimari", "beemari", "bukhar", "ilaj", "ilaaj", "hospital",
                "दवा", "दवाई", "डॉक्टर", "डाक्टर", "बीमारी", "बुखार", "इलाज", "अस्पताल"],
    "legal": ["lawyer", "advocate", "court", "legal", "lawsuit", "sue", "police case", "vakil", "wakil",
              "adalat", "kanooni", "kanuni", "mukadma", "mukadama", "case file",
              "वकील", "अदालत", "कोर्ट", "कानूनी", "क़ानूनी", "मुकदमा", "एफआईआर"],
    "guarantee": ["guarantee", "guaranteed", "guaranty", "surely", "100 percent", "100%", "double my money",
                  "share market", "stock market", "mutual fund", "crypto", "bitcoin", "where should i invest",
                  "where to invest", "invest my money", "investment advice", "pakka", "gaaranti", "garanti",
                  "dugna", "dogna", "kahan nivesh", "paisa double", "paise double", "paisa kahan lagau",
                  "गारंटी", "पक्का", "दोगुना", "दुगना", "कहाँ निवेश", "कहां निवेश", "शेयर बाजार", "शेयर मार्केट",
                  "म्यूचुअल", "क्रिप्टो"],
}

SCHEME_WORDS = ["scheme", "schemes", "yojana", "yojna", "subsidy", "mudra", "pmegp", "svanidhi", "swanidhi",
                "government", "govt", "sarkari", "loan milega", "loan chahiye", "get a loan", "apply for loan",
                "loan kaise", "loan lena", "new loan", "grant",
                "योजना", "योजनाएं", "योजनाएँ", "सब्सिडी", "मुद्रा", "सरकारी", "स्वनिधि", "लोन चाहिए", "लोन मिलेगा",
                "लोन कैसे"]

# Topic words of my_numbers -> the tools to run.
TOPICS = {
    "get_profit_summary": ["profit", "profits", "loss", "earning", "earnings", "income", "sales", "sale", "revenue",
                           "kamai", "munafa", "munaafa", "fayda", "faida", "bikri", "bikree", "ghata", "nuksan",
                           "nuksaan", "kharcha", "kharch", "expenses", "expense", "purchases", "kitna kamaya",
                           "मुनाफा", "मुनाफ़ा", "प्रॉफिट", "लाभ", "कमाई", "बिक्री", "घाटा", "नुकसान", "खर्च", "सेल"],
    "get_forecast": ["forecast", "prediction", "predict", "estimate", "next month", "agle mahine", "anuman",
                     "andaza", "andaaza", "अनुमान", "अंदाज़ा", "अंदाजा", "अगले महीने", "पूर्वानुमान"],
    "get_latest_review": ["review", "decision", "grow", "pivot", "hold", "samiksha", "faisla", "फैसला", "फ़ैसला",
                          "समीक्षा", "रिव्यू"],
    "get_stock_advice": ["stock", "reorder", "inventory", "maal", "saman", "samaan", "order", "khatam",
                         "स्टॉक", "माल", "सामान", "ऑर्डर", "खत्म", "ख़त्म"],
    "get_alerts": ["alert", "alerts", "warning", "warnings", "emi", "instalment", "installment", "kist", "kisht",
                   "due", "chetavani", "चेतावनी", "अलर्ट", "किस्त", "ईएमआई"],
}
GENERAL_NUMBERS = ["how is my shop", "how is my business", "how am i doing", "dukaan kaisi", "dukan kaisi",
                   "business kaisa", "dhandha kaisa", "kaisa chal", "kaisi chal", "दुकान कैसी", "धंधा कैसा",
                   "कैसा चल", "कैसी चल", "my numbers", "summary", "hisab", "hisaab", "हिसाब"]
GENERAL_TOOLS = ["get_profit_summary", "get_alerts", "get_latest_review"]

PERIOD_WORDS = [   # first match wins, so the longer periods come first
    ("last_90_days", ["90 days", "90 din", "3 months", "three months", "3 mahine", "teen mahine", "quarter",
                      "90 दिन", "3 महीने", "तीन महीने"]),
    ("last_30_days", ["30 days", "30 din", "last month and", "past month", "30 दिन"]),
    ("last_month", ["last month", "previous month", "pichhle mahine", "pichle mahine", "pichla mahina",
                    "पिछले महीने", "पिछला महीना"]),
    ("this_month", ["this month", "is mahine", "iss mahine", "is mahina", "इस महीने", "इस माह"]),
]

HOW_PREFIX = ["how do i", "how can i", "how to", "where do i", "where can i", "kaise karu", "kaise karun",
              "kaise kare", "kaise karein", "kaise daalu", "kaise dalu", "kaise likhu", "kahan", "kaise",
              "कैसे", "कहाँ", "कहां"]
APP_WORDS = ["add", "enter", "log", "record", "save", "edit", "change", "update", "delete", "remove", "resolve",
             "mute", "language", "login", "app", "entry", "daalu", "dalu", "daale", "likhu", "likhe", "darj",
             "bhaashaa", "bhasha", "badlu", "badle", "jodu", "jode", "ऐप", "दर्ज", "लिखूं", "लिखूँ", "डालूं",
             "डालूँ", "जोड़ूं", "जोड़ूँ", "बदलूं", "बदलूँ", "भाषा", "एंट्री"]

SMALLTALK = ["hi", "hello", "hey", "namaste", "namaskar", "thanks", "thank you", "thank", "dhanyavad",
             "dhanyawad", "shukriya", "good morning", "good evening", "who are you", "kaun ho", "ok", "okay",
             "bye", "नमस्ते", "नमस्कार", "धन्यवाद", "शुक्रिया", "आप कौन", "तुम कौन"]
SMALLTALK_MAX_TOKENS = 6


@dataclass(frozen=True)
class Route:
    intent: str
    tools: list[tuple[str, dict]] = field(default_factory=list)
    refusal: str | None = None
    period: str | None = None
    via: str = "rules"                 # rules | llm | default


def _norm(text: str) -> str:
    return " " + " ".join(tokens(text)) + " "


def has_any(text: str, norm: str, words: list[str]) -> bool:
    for w in words:
        if any("ऀ" <= c <= "ॿ" for c in w) or not w.replace(" ", "").isalnum():
            if w in text.lower():
                return True
        elif f" {w} " in norm:
            return True
    return False


def period_of(text: str, norm: str) -> str:
    for period, words in PERIOD_WORDS:
        if has_any(text, norm, words):
            return period
    return "this_month"


def by_rules(text: str) -> Route | None:
    norm = _norm(text)
    for kind in REFUSALS:
        if has_any(text, norm, REFUSAL_WORDS[kind]):
            return Route("out_of_scope", refusal=kind)
    if has_any(text, norm, SCHEME_WORDS):
        return Route("schemes", tools=[("match_schemes", {})])
    if has_any(text, norm, HOW_PREFIX) and has_any(text, norm, APP_WORDS):
        return Route("how_to")
    names = [name for name, words in TOPICS.items() if has_any(text, norm, words)]
    if not names and has_any(text, norm, GENERAL_NUMBERS):
        names = GENERAL_TOOLS
    if names:
        period = period_of(text, norm)
        return Route("my_numbers", period=period,
                     tools=[(n, {"period": period} if n == "get_profit_summary" else {}) for n in names])
    if len(norm.split()) <= SMALLTALK_MAX_TOKENS and has_any(text, norm, SMALLTALK):
        return Route("smalltalk")
    return None


def by_llm(text: str, client: LLMClient, classify_prompt: str) -> Route:
    """The model only picks a label; numbers questions it labels my_numbers get the general tool set."""
    try:
        label = client.generate("You classify messages.", [{"role": "user", "content": classify_prompt}],
                                max_tokens=5, temperature=0.0).strip().lower().strip(".'\"` ")
    except LLMError as e:
        log.info("router llm fallback failed kind=%s", e.kind)
        return Route("out_of_scope", via="default")
    if label not in INTENTS:
        return Route("out_of_scope", via="default")
    if label == "my_numbers":
        return Route(label, via="llm", period="this_month",
                     tools=[(n, {"period": "this_month"} if n == "get_profit_summary" else {}) for n in GENERAL_TOOLS])
    if label == "schemes":
        return Route(label, via="llm", tools=[("match_schemes", {})])
    return Route(label, via="llm")


def route(text: str, client: LLMClient | None = None) -> Route:
    r = by_rules(text)
    if r is not None:
        return r
    if client is None:
        return Route("out_of_scope", via="default")
    from app.llm import prompts
    return by_llm(text, client, prompts.classify_prompt(text))
