"""One chat turn (C-07): language -> route -> tools -> template -> LLM -> guard -> store. Code decides; the LLM only
rephrases the template built from the same facts (DEC-06, DEC-78), and the guard checks the result (DEC-76).

Smalltalk, refusals, out-of-scope and scheme answers without a KB are templates with no LLM call (DEC-77).
Each turn is answered on its own; earlier turns are stored but not sent (DEC-77). Nothing here logs the question,
the prompt or the answer: only intent, language and outcome kinds.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.llm import client as llm
from app.llm import guard, prompts, templates, tools
from app.llm.language import detect
from app.llm.router import route
from app.models import ChatMessage, Shop
from app.services import clock

log = logging.getLogger(__name__)

LLM_INTENTS = {"my_numbers", "how_to"}


@dataclass
class Turn:
    text: str
    language: str
    intent: str
    guard: str                  # passed | failed | template | llm_unavailable
    sources: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    message_id: int | None = None
    cached: bool = False
    refusal: str | None = None
    via: str = "rules"


def sources_of(tool_outputs: list[dict]) -> list[dict]:
    """One entry per tool output: where the facts come from, and the facts themselves (each with its label)."""
    out = []
    for o in tool_outputs:
        src = o.get("source") or {}
        out.append({"id": src.get("id"), "label": src.get("label"), "tool": o.get("tool"), "as_of": o.get("as_of"),
                    "is_estimate": bool(o.get("is_estimate")), "note": o.get("note"),
                    "facts": [{"key": f["key"], "value": f["value"], "unit": f["unit"], "period": f.get("period"),
                               "source_label": src.get("label")} for f in o.get("facts", [])]})
    return out


def run_tools(db: Session, user_id: int, shop: Shop, intent: str, wanted: list[tuple[str, dict]], question: str,
              today: date) -> list[dict]:
    if intent == "how_to":
        return [prompts.help_output(question)]
    return [tools.run(db, user_id, shop.id, name, today=today, **args) for name, args in wanted]


def answer(db: Session, user_id: int, shop: Shop, question: str, *, client: llm.LLMClient | None = None,
           today: date | None = None, cache: llm.AnswerCache | None = None) -> Turn:
    today = today or clock.today()
    cache = llm.answer_cache if cache is None else cache
    client = client or llm.get_client()
    lang = detect(question)
    r = route(question, client)
    outs = run_tools(db, user_id, shop, r.intent, r.tools, question, today)
    draft = templates.render(r.intent, outs, lang, r.refusal)
    turn = Turn(draft, lang, r.intent, "template", sources_of(outs), refusal=r.refusal, via=r.via)

    if r.intent in LLM_INTENTS and not r.refusal:
        system, msgs = prompts.build(r.intent, lang, question, outs, draft)
        facts_json = json.dumps(prompts.facts_payload(r.intent, lang, "", outs), ensure_ascii=False, sort_keys=True,
                                default=str)
        key = cache.key(shop.id, today, question, facts_json)
        hit = cache.get(key)
        if hit is not None:
            turn.text, turn.guard, turn.cached = hit, "passed", True
        else:
            text, failure = llm.generate_or_fallback(client, system, msgs, fallback=lambda: draft)
            if failure:
                turn.guard, turn.failures = "llm_unavailable", [failure]
            else:
                shown, failures = guard.apply(text, draft, question=question, language=lang, tool_outputs=outs)
                turn.text, turn.failures = shown, failures
                turn.guard = "failed" if failures else "passed"
                if not failures:
                    cache.put(key, shown)
    log.info("chat turn intent=%s language=%s via=%s guard=%s cached=%s", r.intent, lang, r.via, turn.guard,
             turn.cached)

    db.add(ChatMessage(shop_id=shop.id, role="user", text=question, sources_json=[]))
    msg = ChatMessage(shop_id=shop.id, role="assistant", text=turn.text, sources_json=turn.sources)
    db.add(msg)
    db.commit()
    turn.message_id = msg.id
    return turn
