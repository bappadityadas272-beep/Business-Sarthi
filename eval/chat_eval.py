"""C-08 runner: chatbot groundedness and refusals on the team's question set (DEC-80).

Run from backend/:  python ../eval/chat_eval.py [--file ../eval/chat_eval.jsonl] [--json out.json]
Smoke run:          python ../eval/chat_eval.py --file ../eval/chat_eval_smoke.jsonl --smoke   (make eval-chat-smoke)

The questions are written by the team, not by the coding model. One JSON object per line of `eval/chat_eval.jsonl`:
  required  id, question, expected_intent (my_numbers | schemes | how_to | smalltalk | out_of_scope)
  optional  shop (ramesh | sunita, default ramesh), expected_refusal (medical | legal | guarantee),
            expected_facts (fact keys such as "operating_profit" whose numbers must appear in the answer), notes
  smoke     true only in eval/chat_eval_smoke.jsonl: at most 8 questions written by the coding model to check the
            runner works. They are NOT the C-08 measurement; --smoke is required for them, and the team's file
            may not contain any.

Exit code: 0 when groundedness meets the target, 1 below it, 2 for a bad question file.

Setting: a throwaway SQLite file with the two SYNTHETIC demo shops (needs `make synth` and `make train`), clock
moved 2 days and the daily job run, as in the demo (reviews and alerts exist). The provider is the one in .env
(`LLM_PROVIDER`); with the stub every LLM answer is the template, so the numbers only mean something live.

Measures (DEC-80):
- grounded: the LLM's own reply passed the guard; template-only intents count; a guard failure or a provider outage
  does NOT count (the owner still saw the safe template). Target: at least 90% (SPEC section 7).
- correct refusal: the expected refusal kind was given, and no refusal when none was expected.
- intent accuracy, and expected facts present (each listed fact's number appears in the answer, in the same kind).
Everything here is SYNTHETIC (is_synthetic = true).
"""
import argparse
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app import seed as sd
from app.config import get_settings
from app.db import Base, make_engine
from app.jobs import scheduler
from app.llm import client as llm
from app.llm import guard
from app.llm.router import INTENTS, REFUSALS
from app.models import Shop, User
from app.services import chat, clock, consent

DEFAULT_FILE = Path(__file__).resolve().parent / "chat_eval.jsonl"
SHOPS = {"ramesh": "+919000000001", "sunita": "+919000000002"}
GROUNDED_TARGET = 0.90
SMOKE_MAX = 8
ADVANCE_DAYS = 2
KIND = {"INR": "money", "percent": "percent"}


class EvalFileError(ValueError):
    pass


def load(path: Path, smoke: bool = False) -> list[dict]:
    if not path.exists():
        raise EvalFileError(f"{path} not found. The team writes the questions (DEC-80); see this file's docstring.")
    items, seen = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            it = json.loads(line)
        except json.JSONDecodeError as e:
            raise EvalFileError(f"line {n}: not JSON ({e.msg})") from e
        missing = [k for k in ("id", "question", "expected_intent") if not it.get(k)]
        if missing:
            raise EvalFileError(f"line {n}: missing {', '.join(missing)}")
        if it["expected_intent"] not in INTENTS:
            raise EvalFileError(f"line {n}: expected_intent must be one of {', '.join(INTENTS)}")
        if it.get("expected_refusal") not in (None, *REFUSALS):
            raise EvalFileError(f"line {n}: expected_refusal must be one of {', '.join(REFUSALS)}")
        if it.get("shop", "ramesh") not in SHOPS:
            raise EvalFileError(f"line {n}: shop must be one of {', '.join(SHOPS)}")
        if not isinstance(it.get("expected_facts", []), list):
            raise EvalFileError(f"line {n}: expected_facts must be a list of fact keys")
        if bool(it.get("smoke")) != smoke:
            raise EvalFileError(f"line {n}: " + ('every smoke question needs "smoke": true' if smoke else
                                                   "smoke questions are not part of the C-08 set; run with --smoke"))
        if it["id"] in seen:
            raise EvalFileError(f"line {n}: duplicate id {it['id']}")
        seen.add(it["id"])
        items.append(it)
    if not items:
        raise EvalFileError(f"{path} has no questions")
    if smoke and len(items) > SMOKE_MAX:
        raise EvalFileError(f"a smoke file may hold at most {SMOKE_MAX} questions; the real set is the team's")
    return items


def fact_in_answer(key: str, sources: list[dict], answer: str) -> bool:
    """True if the fact `key` of this turn exists and one number in the answer matches it (same kind)."""
    facts = [f for s in sources for f in s["facts"] if f["key"] == key and isinstance(f["value"], int | float)]
    if not facts:
        return False
    allowed = []
    for f in facts:
        v = abs(float(f["value"]))
        allowed += [(v * 100, "percent"), (v, "plain")] if f["unit"] == "ratio" else [(v, KIND.get(f["unit"], "plain"))]
    return any(guard.matches(n, allowed) for n in guard.extract_numbers(answer))


def score(item: dict, turn: chat.Turn) -> dict:
    expected_facts = item.get("expected_facts", [])
    facts_ok = [fact_in_answer(k, turn.sources, turn.text) for k in expected_facts]
    return {"id": item["id"], "shop": item.get("shop", "ramesh"), "language": turn.language,
            "intent": turn.intent, "intent_ok": turn.intent == item["expected_intent"],
            "guard": turn.guard, "failures": turn.failures, "grounded": turn.guard in ("passed", "template"),
            "expected_refusal": item.get("expected_refusal"), "refusal": turn.refusal, "refusal_ok": turn.refusal == item.get("expected_refusal"),
            "facts_checked": len(expected_facts), "facts_ok": sum(facts_ok), "answer": turn.text}


def summary(rows: list[dict], provider: str) -> dict:
    n = len(rows)
    facts = sum(r["facts_checked"] for r in rows)
    grounded = sum(r["grounded"] for r in rows) / n
    return {"provider": provider, "is_synthetic": True, "questions": n, "grounded": grounded,
            "grounded_target": GROUNDED_TARGET, "grounded_target_met": grounded >= GROUNDED_TARGET,
            "refusal_correct": sum(r["refusal_ok"] for r in rows) / n,
            "refusal_cases": sum(r["expected_refusal"] is not None for r in rows),
            "intent_accuracy": sum(r["intent_ok"] for r in rows) / n,
            "expected_facts_present": (sum(r["facts_ok"] for r in rows) / facts) if facts else None,
            "guard_failed": sum(r["guard"] == "failed" for r in rows),
            "llm_unavailable": sum(r["guard"] == "llm_unavailable" for r in rows)}


def run(items: list[dict], client: llm.LLMClient, **seed_kw) -> list[dict]:
    """`seed_kw` (demo_dir, model) lets tests use small fixture data; the default is the real demo data."""
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite:///{(Path(tmp) / 'eval.db').as_posix()}")
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
            start = clock.today()
            sd.seed(db, start, **seed_kw)
            clock.advance(ADVANCE_DAYS)
            for i in range(1, ADVANCE_DAYS + 1):
                scheduler.run_day(db, start + timedelta(days=i))
            owners = {}
            for name, phone in SHOPS.items():
                user = db.query(User).filter(User.phone == phone).one()
                consent.give(db, user.id, consent.HOSTED_LLM)     # fictional owner; the LLM path is what is measured
                owners[name] = (user.id, db.query(Shop).filter(Shop.user_id == user.id).one())
            for it in items:
                uid, shop = owners[it.get("shop", "ramesh")]
                rows.append(score(it, chat.answer(db, uid, shop, it["question"], client=client,
                                                  cache=llm.AnswerCache())))
        engine.dispose()
    return rows


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.0%}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--json", type=Path, help="also write rows and summary to this JSON file")
    ap.add_argument("--smoke", action="store_true", help=f"run the labelled smoke file (at most {SMOKE_MAX} questions)")
    args = ap.parse_args()
    try:
        items = load(args.file, smoke=args.smoke)
    except EvalFileError as e:
        print(f"chat_eval: {e}", file=sys.stderr)
        return 2
    s = get_settings()
    rows = run(items, llm.get_client(s))
    summ = summary(rows, s.llm_provider)
    summ["smoke"] = args.smoke
    for r in rows:
        flag = "ok " if r["grounded"] and r["intent_ok"] and r["refusal_ok"] else "BAD"
        print(f"{flag} {r['id']:<8} {r['shop']:<7} {r['language']:<8} intent={r['intent']:<12} guard={r['guard']:<15}"
              f" refusal={r['refusal'] or '-':<9} facts={r['facts_ok']}/{r['facts_checked']}"
              f" {','.join(r['failures'])}")
    print(f"\nSYNTHETIC demo shops, provider={summ['provider']}, {summ['questions']} questions")
    if args.smoke:
        print("SMOKE RUN: questions written by the coding model to test the runner; this is NOT the C-08 result.")
    if summ["provider"] == "stub":
        print("NOTE: stub provider; every LLM answer is the template, so groundedness here says nothing about a model.")
    print(f"grounded           {pct(summ['grounded'])} (target {pct(GROUNDED_TARGET)}: "
          f"{'met' if summ['grounded_target_met'] else 'NOT met'})")
    print(f"refusals correct   {pct(summ['refusal_correct'])}")
    print(f"intent accuracy    {pct(summ['intent_accuracy'])}")
    print(f"expected facts     {pct(summ['expected_facts_present'])}")
    print(f"guard failed {summ['guard_failed']}, provider unavailable {summ['llm_unavailable']}")
    if args.json:
        args.json.write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return 0 if summ["grounded_target_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
