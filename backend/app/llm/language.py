"""Reply language (C-05, DEC-77): Devanagari script = `hi`; Latin script with Hindi words = `hinglish` (answered in
Latin script); otherwise `en`. Pure rules, no model."""
import re
from typing import Literal

Language = Literal["hi", "hinglish", "en"]
LANGUAGES: tuple[str, ...] = ("hi", "hinglish", "en")

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
TOKEN = re.compile(r"[a-z0-9ऀ-ॿ]+")

# Romanised Hindi words that are not English words: one is enough.
STRONG = frozenset(["hai", "hain", "hoon", "hun", "tha", "thi", "kya", "kitna", "kitni", "kitne", "mera", "meri", "mere", "mujhe", "mujhko", "hamara", "hamari", "humara", "kaise", "kaisa", "kaisi", "kaun", "kab", "kahan", "kyun", "kyon", "kyu", "mahine", "mahina", "mahinon", "nahi", "nahin", "nhi", "hoga", "hogi", "honge", "karo", "karna", "karu", "karun", "karen", "kijiye", "batao", "bataiye", "bataye", "bata", "aaj", "kal", "paisa", "paise", "rupaye", "dukaan", "dukan", "munafa", "munaafa", "kamai", "bikri", "bikree", "maal", "saman", "samaan", "chahiye", "milega", "milegi", "sakta", "sakti", "sakte", "raha", "rahi", "rahe", "wala", "wali", "abhi", "pichhle", "pichle", "agle", "agla", "kripya", "dhanyavad", "dhanyawad", "shukriya", "namaste", "namaskar", "theek", "thik", "accha", "acha", "achha", "yojana", "kist", "kisht", "karz", "karza", "karja", "bahut", "kuch", "kuchh", "koi", "aur", "lekin", "haan", "dijiye", "dikhao", "dekho", "samjhao", "jaldi", "kharcha", "kharch", "udhaar", "udhar", "bechna", "becha", "khareed", "kharida", "ghata", "nuksan", "nuksaan", "sarkari", "bolo", "liye", "kaunsa", "kaunsi", "kaunse", "lun", "loon", "lagau", "dena", "deni", "lena", "leni", "chal"])
# Short words that are only Hindi with company: two are needed.
WEAK = frozenset(["ka", "ki", "ke", "ko", "se", "mein", "ye", "yeh", "wo", "woh", "ji", "bhai"])


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def detect(text: str) -> Language:
    dev, lat = len(DEVANAGARI.findall(text)), len(LATIN.findall(text))
    if dev and dev * 2 >= lat:
        return "hi"
    toks = tokens(text)
    strong = sum(t in STRONG for t in toks)
    weak = sum(t in WEAK for t in toks)
    return "hinglish" if strong >= 1 or weak >= 2 else "en"


def script_of(text: str) -> Literal["devanagari", "latin", "none"]:
    """The main script of a reply; the guard (C-06) checks it against the question's language."""
    dev, lat = len(DEVANAGARI.findall(text)), len(LATIN.findall(text))
    if not dev and not lat:
        return "none"
    return "devanagari" if dev >= lat else "latin"


def expected_script(lang: Language) -> Literal["devanagari", "latin"]:
    return "devanagari" if lang == "hi" else "latin"
