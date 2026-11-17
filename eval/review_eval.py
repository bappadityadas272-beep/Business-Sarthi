"""ML5 review engine on the 20 hand-labelled scenarios (M-08), plus the status of the ML_PLAN section 8 targets that
cannot be measured yet (ML7, ML8, the public-data method check), and a one-table summary of every target.

Run from backend/:  python ../eval/review_eval.py [--write]

The scenarios are `backend/tests/review_scenarios.yaml`: inputs and expected decisions worked out by hand, not
copied from the program. They are the same cases as tests/test_review.py; this script only reports the result.
Nothing here is tuned; a mismatch is reported, never fixed by changing a threshold.
The summary table reads the "Target" line that each other evaluation part already wrote, so `make eval` must run
before this script for the summary to be current.
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parts import PARTS, REPORT, refresh_report, write_part

from app.ml import review as engine
from app.rules import get_rules

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "backend" / "tests" / "review_scenarios.yaml"
START, END = date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=89)


def build_logs(sc: dict) -> dict[date, dict]:
    """Same construction as tests/test_review.py (see the header of review_scenarios.yaml)."""
    logs, step = {}, 2 if sc.get("pattern") == "alternate" else 1
    for b, block in enumerate(sc["blocks"]):
        for i in range(block["logged"]):
            day = START + timedelta(days=30 * b + i * step)
            logs[day] = {"sales": float(block["sales"]), "purchases": float(block["purchases"]),
                         "expenses": float(block["expenses"]) if i == 0 else 0.0}
    return logs


def run(sc: dict) -> dict:
    rules = get_rules()
    months = None if sc["p50_per_day"] is None else [{"start": START, "end": END, "p50": sc["p50_per_day"] * 90}]
    return engine.review(period_end=END, rule=rules.review, actions=rules.actions, logs=build_logs(sc),
                         forecast_months=months, monthly_emi=sc["emi"], cash=sc["cash"])


def ml5_part() -> tuple[str, bool]:
    scenarios = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    rows, agree = [], 0
    for sc in scenarios:
        out = run(sc)
        ok = out["decision"] == sc["expect"]["decision"]
        agree += ok
        reasons = ", ".join(r["indicator"] for r in out["reasons"]) or "-"
        rows.append(f"| {sc['name']} | {sc['expect']['decision']} | {out['decision']} | {reasons} | "
                    f"{out['confidence']} | {'yes' if ok else '**NO**'} |")
    n = len(scenarios)
    met = agree == n == 20
    lines = [
        "## ML5 grow / hold / pivot review (M-08)", "",
        ("- Engine `app/ml/review.py` with the thresholds of `data/rules/review_rules.yaml` as they are (initial "
        "assumptions of ML_PLAN, untested on real shops)."),
        ("- Cases: `backend/tests/review_scenarios.yaml`, 20 scenarios written and worked out by hand (each has a "
        "`why` with the arithmetic). They are rule-checking cases, not shop data."), "",
        "### Target", "",
        (f"100% agreement with the hand-labelled decisions on 20 cases (ML_PLAN section 8): "
        f"**{'MET' if met else 'MISSED'}** ({agree} of {n})."), "",
        "### Scenarios", "",
        "| Scenario | Expected | Engine | Reasons given | Confidence | Agrees |",
        "|---|---|---|---|---|---|", *rows, "",
        "### Notes and honest reading", "",
        ("- **This checks the rules, not the advice.** The cases and the code come from the same written rules, so "
        "full agreement shows the code does what the rules say, including at each threshold edge. It does not show "
        "that the thresholds (DSCR 1.0 and 1.5, revenue at 60% and 100% of P50, 30 days of runway, 70% logged days) "
        "are right for real kirana shops; that needs owners' outcomes we do not have."),
        ("- **The cases were written by the coding model** in the M-08 session and checked by hand arithmetic; no "
        "shop owner or domain expert has reviewed them. Some details of DEC-66 still await the human's confirmation."),
        "- Decisions on the demo shops (SYNTHETIC data) are shown by `scripts/demo_run.py` step 6, not scored here.", "",
    ]
    return "\n".join(lines), met


def open_part() -> str:
    kb = REPO / "data" / "kb" / "schemes.json"
    chat = REPO / "eval" / "chat_eval.jsonl"
    public = REPO / "data" / "PUBLIC_DATA.md"
    return "\n".join([
        "## ML7, ML8 and the public-data check: not measured yet", "",
        ("These ML_PLAN section 8 targets have **no result**. They are listed so that a missing number is not "
        "mistaken for a met target."), "",
        "| Target | Status | What is missing | Who |",
        "|---|---|---|---|",
        (f"| ML7: top-3 holds the expected scheme for at least 80% of 20 owner profiles | NOT MEASURED | "
        f"`data/kb/schemes.json` {'exists' if kb.is_file() else 'does not exist'} (D-03). `tests/test_schemes.py` "
        f"gives 20/20, but on a test-only fixture whose profiles were written in the same session, with the "
        f"fallback embedder: that proves the code path, not matching quality. | Team: the KB (D-03) and 20 real "
        f"profiles |"),
        (f"| ML8: grounded in at least 90%, correct refusals in at least 90% of 30 questions | NOT MEASURED | "
        f"`eval/chat_eval.jsonl` {'exists' if chat.is_file() else 'does not exist'} (C-08 BLOCKED). The 8-question "
        f"smoke set (written by the coding model, labelled `smoke: true`) gave grounded 7/8 = 88%, below the "
        f"target, refusals 8/8, with Gemini on 2026-11-17; the one miss was a provider outage. That is a smoke "
        f"check, not this target. | Team: the 30 questions |"),
        (f"| Public dataset: quantile GBM + conformal reaches 75% to 85% coverage and beats seasonal-naive | NOT "
        f"MEASURED | `data/PUBLIC_DATA.md` {'exists' if public.is_file() else 'does not exist'} (D-02, licence "
        f"check). This is the only planned evidence of real-world behaviour, so **there is none yet**. | Team: "
        f"D-02 |"),
        "",
    ])


TARGET_RE = re.compile(r"\*\*(MET|MISSED|NOT MET)\*\*")


def summary_part(ml5_met: bool) -> str:
    def status(name: str) -> str:
        p = PARTS / f"{name}.md"
        if not p.is_file():
            return "NO RESULT (run `make eval`)"
        text = p.read_text(encoding="utf-8")
        sec = text.split("### Target", 1)[-1].split("###", 1)[0]
        m = TARGET_RE.search(sec)
        return m.group(1) if m else "NO RESULT"

    head = REPORT.read_text(encoding="utf-8").split("<!--", 1)[0] if REPORT.is_file() else ""
    ml2 = [f"{m.group(2)}" for m in re.finditer(r"^\| (WAPE at least|P10 to P90 coverage)[^|]*\|[^|]*\| (\w+) \|$",
                                                   head, re.MULTILINE)]
    ml2_wape, ml2_cov = (ml2 + ["NO RESULT", "NO RESULT"])[:2]
    rows = [
        ("ML2 WAPE at least 10% below the peer median", ml2_wape, "synthetic"),
        ("ML2 pinball loss reported, lower than the \"unconstrained baseline\"",
         "PARTLY: reported and below the peer-quantile baseline at P10, P50 and P90; the \"unconstrained "
         "baseline\" is not defined in the docs and no model without the monotone constraints was compared"
         if "Pinball loss" in head else "NO RESULT", "synthetic"),
        ("ML2 P10 to P90 coverage 75% to 85%", ml2_cov, "synthetic"),
        ("ML3 blend beats prior-only only after 2 months", status("ml3_reforecast"), "synthetic"),
        ("ML4 fewer stock-outs, stock at most +25%", status("ml4_stock"), "synthetic"),
        ("ML5 20 hand-labelled scenarios, 100% agreement", "MET" if ml5_met else "MISSED", "hand-written cases"),
        ("ML6 recall at least 90%, under 1 false alarm per shop-month", status("ml6_alerts"), "synthetic"),
        ("ML7 top-3 scheme match at least 80%", "NOT MEASURED", "needs the team's KB"),
        ("ML8 grounded and refusals at least 90%", "NOT MEASURED", "needs the team's 30 questions"),
        ("Public-data method check", "NOT MEASURED", "needs D-02"),
    ]
    return "\n".join([
        "## Summary of every ML_PLAN section 8 target", "",
        ("Every MET result above is on SYNTHETIC data or hand-written cases: it shows the method and the code behave "
        "as designed, not that the advice is right for real shops. No real-world accuracy has been measured."), "",
        "| Target | Status | Measured on |", "|---|---|---|",
        *[f"| {a} | {b} | {c} |" for a, b, c in rows], "",
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the report parts and refresh docs/EVAL_REPORT.md")
    args = ap.parse_args()
    ml5, met = ml5_part()
    opened, summary = open_part(), summary_part(met)
    print(ml5, opened, summary, sep="\n")
    print(f"ML5 target met: {met}")
    if args.write:
        write_part("ml5_review", ml5)
        write_part("ml7_ml8_public", opened)
        write_part("zz_summary", summary)
        refresh_report()
        print("wrote the ML5, open-targets and summary parts and refreshed docs/EVAL_REPORT.md")
    if not met:
        sys.exit(1)


if __name__ == "__main__":
    main()
