"""C-08 runner (not the question set: the team writes eval/chat_eval.jsonl, DEC-80). The lines below only exercise
the runner and are not evaluation questions."""
import json

import pytest

from app.llm.stub import StubClient
from app.services.chat import Turn
from tests.conftest import load_script

ev = load_script("chat_eval", "eval/chat_eval.py")


def write(tmp_path, lines):
    p = tmp_path / "set.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else x for x in lines),
                 encoding="utf-8")
    return p


@pytest.mark.parametrize(("line", "msg"), [
    ("not json", "not JSON"),
    ({"id": "a", "question": "x"}, "missing expected_intent"),
    ({"id": "a", "question": "x", "expected_intent": "weather"}, "expected_intent must be"),
    ({"id": "a", "question": "x", "expected_intent": "out_of_scope", "expected_refusal": "tax"}, "expected_refusal"),
    ({"id": "a", "question": "x", "expected_intent": "my_numbers", "shop": "gopal"}, "shop must be"),
    ({"id": "a", "question": "x", "expected_intent": "my_numbers", "expected_facts": "sales"}, "list of fact keys"),
])
def test_bad_lines_are_rejected_with_the_line_number(tmp_path, line, msg):
    with pytest.raises(ev.EvalFileError, match=msg):
        ev.load(write(tmp_path, [line]))


def test_missing_file_and_duplicates(tmp_path):
    with pytest.raises(ev.EvalFileError, match="team writes the questions"):
        ev.load(tmp_path / "nope.jsonl")
    dup = {"id": "a", "question": "x", "expected_intent": "smalltalk"}
    with pytest.raises(ev.EvalFileError, match="duplicate id"):
        ev.load(write(tmp_path, [dup, dup]))


def turn(guard="passed", intent="my_numbers", refusal=None, text="Munafa ₹25,456 hai.", value=25456.4):
    src = [{"id": "daily_logs", "label": "logs", "tool": "get_profit_summary", "as_of": None, "is_estimate": False,
            "note": None, "facts": [{"key": "operating_profit", "value": value, "unit": "INR", "period": None,
                                     "source_label": "logs"}]}]
    return Turn(text, "hinglish", intent, guard, src, refusal=refusal)


def test_scoring_follows_dec_80():
    item = {"id": "a", "question": "x", "expected_intent": "my_numbers", "expected_facts": ["operating_profit", "nope"]}
    r = ev.score(item, turn())
    assert r["grounded"] and r["intent_ok"] and r["refusal_ok"] and (r["facts_ok"], r["facts_checked"]) == (1, 2)
    assert not ev.score(item, turn(guard="failed"))["grounded"]              # the safe template does not count
    assert not ev.score(item, turn(guard="llm_unavailable"))["grounded"]
    assert ev.score({**item, "expected_intent": "smalltalk"}, turn(guard="template", intent="smalltalk"))["grounded"]
    ref = {"id": "b", "question": "x", "expected_intent": "out_of_scope", "expected_refusal": "medical"}
    assert ev.score(ref, turn(guard="template", intent="out_of_scope", refusal="medical"))["refusal_ok"]
    assert not ev.score(ref, turn(guard="template", intent="out_of_scope"))["refusal_ok"]
    assert not ev.score(item, turn(refusal="legal"))["refusal_ok"]          # refused when it should not
    s = ev.summary([ev.score(item, turn()), ev.score(item, turn(guard="failed"))], "stub")
    assert s["grounded"] == 0.5 and not s["grounded_target_met"] and s["guard_failed"] == 1 and s["is_synthetic"]


def test_runs_end_to_end_with_the_stub(client, synth_small, model_small, tmp_path):
    items = ev.load(write(tmp_path, [
        {"id": "r1", "question": "Is mahine ka profit kitna hai?", "expected_intent": "my_numbers",
         "expected_facts": ["operating_profit"]},
        {"id": "r2", "question": "namaste", "expected_intent": "smalltalk", "shop": "sunita"},
    ]))
    rows = ev.run(items, StubClient(), demo_dir=synth_small / "demo", model=model_small)
    s = ev.summary(rows, "stub")
    assert s["grounded"] == 1.0 and s["intent_accuracy"] == 1.0 and s["expected_facts_present"] == 1.0, rows


def test_smoke_rules(tmp_path):
    smoke = {"id": "s1", "smoke": True, "question": "x", "expected_intent": "smalltalk"}
    real = {"id": "r1", "question": "x", "expected_intent": "smalltalk"}
    with pytest.raises(ev.EvalFileError, match="run with --smoke"):
        ev.load(write(tmp_path, [real, smoke]))                        # the team's set may not hide smoke lines
    with pytest.raises(ev.EvalFileError, match="needs"):
        ev.load(write(tmp_path, [smoke, real]), smoke=True)
    many = [{**smoke, "id": f"s{i}"} for i in range(ev.SMOKE_MAX + 1)]
    with pytest.raises(ev.EvalFileError, match=f"at most {ev.SMOKE_MAX}"):
        ev.load(write(tmp_path, many), smoke=True)


def test_shipped_smoke_file_is_labelled_and_runs(synth_small, model_small):
    items = ev.load(ev.DEFAULT_FILE.with_name("chat_eval_smoke.jsonl"), smoke=True)
    assert len(items) <= ev.SMOKE_MAX and all("SMOKE ONLY" in it["notes"] for it in items)
    rows = ev.run(items, StubClient(), demo_dir=synth_small / "demo", model=model_small)
    s = ev.summary(rows, "stub")
    assert s["intent_accuracy"] == 1.0 and s["refusal_correct"] == 1.0, [(r["id"], r["intent"], r["refusal"]) for r in rows]
    assert s["refusal_cases"] == 2


def test_exit_code_follows_the_target(monkeypatch, tmp_path, capsys):
    p = write(tmp_path, [{"id": "a", "question": "x", "expected_intent": "smalltalk"}])
    row = ev.score({"id": "a", "question": "x", "expected_intent": "smalltalk"}, turn(guard="failed", intent="smalltalk"))
    monkeypatch.setattr(ev, "run", lambda items, client: [row])
    monkeypatch.setattr("sys.argv", ["chat_eval", "--file", str(p)])
    assert ev.main() == 1 and "NOT met" in capsys.readouterr().out
    monkeypatch.setattr(ev, "run", lambda items, client: [{**row, "grounded": True}])
    assert ev.main() == 0
    monkeypatch.setattr("sys.argv", ["chat_eval", "--file", str(tmp_path / "none.jsonl")])
    assert ev.main() == 2
