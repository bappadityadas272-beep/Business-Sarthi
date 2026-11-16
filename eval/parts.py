"""docs/EVAL_REPORT.md = the ML2 section (forecast_eval.py) followed by one part per later model.
Each evaluation script writes its own part to eval/report_parts/<name>.md; `merge` puts them after the ML2 text."""
from pathlib import Path

PARTS = Path(__file__).with_name("report_parts")
REPORT = Path(__file__).resolve().parents[1] / "docs" / "EVAL_REPORT.md"
MARK = "<!-- parts below are written by eval/*_eval.py; do not edit by hand -->"


def write_part(name: str, text: str) -> Path:
    PARTS.mkdir(exist_ok=True)
    path = PARTS / f"{name}.md"
    path.write_text(text.strip() + "\n", encoding="utf-8", newline="\n")
    return path


def merge(report_text: str) -> str:
    """The report text with every part appended (any parts already in the text are replaced)."""
    head = report_text.split(MARK)[0].rstrip()
    parts = [p.read_text(encoding="utf-8").strip() for p in sorted(PARTS.glob("*.md"))] if PARTS.is_dir() else []
    return "\n\n".join([head, MARK, *parts]) if parts else head


def refresh_report() -> None:
    if REPORT.is_file():
        REPORT.write_text(merge(REPORT.read_text(encoding="utf-8")) + "\n", encoding="utf-8", newline="\n")
