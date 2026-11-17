"""Prompt files and the prompt builder (C-05).

The user message the LLM gets is `<facts>{json}</facts>` and `<draft>...</draft>`. The JSON holds the intent, the
reply language, the owner's question and this turn's tool outputs. Owner-typed text (the question, item names) only
ever appears inside that JSON, escaped (DEC-76). The stub provider re-renders the template from the same JSON.
"""
import json
from functools import cache
from pathlib import Path

import yaml

from app.llm.client import Message
from app.llm.language import Language
from app.llm.router import has_any, tokens

DIR = Path(__file__).parent
HELP_FILE = DIR.parent / "app_help.yaml"
LANGUAGE_NAMES = {
    "hi": "Hindi in Devanagari script",
    "hinglish": "Hinglish: Hindi words written in Latin (English) letters, not Devanagari",
    "en": "simple English",
}


@cache
def load(name: str) -> str:
    return (DIR / name).read_text(encoding="utf-8")


@cache
def app_help() -> dict:
    return yaml.safe_load(HELP_FILE.read_text(encoding="utf-8"))


def system_prompt(language: Language) -> str:
    return load("system.md").replace("{language_name}", LANGUAGE_NAMES[language])


def classify_prompt(question: str) -> str:
    q = json.dumps(question, ensure_ascii=False).replace("</", "<\\/")
    return load("classify.md").replace("{question_json}", q)


def help_output(question: str) -> dict:
    """The how_to "tool": the best matching app-help topic (most keyword hits), or the fallback list."""
    data = app_help()
    norm = " " + " ".join(tokens(question)) + " "
    scored = [(sum(has_any(question, norm, [k]) for k in t["keywords"]), name) for name, t in data["topics"].items()]
    hits, topic = max(scored, default=(0, None))
    entry = data["topics"][topic] if hits else data["fallback"]
    return {"tool": "app_help", "source": {"id": "app_help", "label": "Business Sarthi app help"},
            "is_estimate": False, "note": None if hits else "no_topic", "facts": [],
            "data": {"topic": topic if hits else None, "text": {k: entry[k] for k in ("en", "hinglish", "hi")}}}


def facts_payload(intent: str, language: Language, question: str, tool_outputs: list[dict]) -> dict:
    return {"intent": intent, "language": language, "question": question, "tools": tool_outputs}


def build(intent: str, language: Language, question: str, tool_outputs: list[dict],
          draft: str) -> tuple[str, list[Message]]:
    payload = json.dumps(facts_payload(intent, language, question, tool_outputs), ensure_ascii=False,
                         separators=(",", ":"))
    # "</" inside data must not close a tag early: JSON allows "<\/".
    payload, draft = payload.replace("</", "<\\/"), draft.replace("</", "< /")
    user = f"<facts>{payload}</facts>\n<draft>{draft}</draft>"
    return system_prompt(language), [{"role": "user", "content": user}]
