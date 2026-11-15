#!/usr/bin/env python3
"""Regenerate docs/MASTER.md from AGENTS.md and the docs. Never edit MASTER.md by hand."""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["AGENTS.md", "docs/CHECKPOINTS.md", "docs/SPEC.md", "docs/ARCHITECTURE.md",
         "docs/ML_PLAN.md", "docs/DECISIONS.md", "docs/CHANGELOG.md"]

def main() -> None:
    parts = [
        "# Business Sarthi: MASTER (generated)\n",
        f"> Generated on {date.today().isoformat()} by `tools/build_master.py`. **Do not edit by hand.** "
        "Edit the source files, then run `python tools/build_master.py`.\n",
        "> Contents: " + ", ".join(f"`{p}`" for p in ORDER) + ".\n",
    ]
    for rel in ORDER:
        text = (ROOT / rel).read_text(encoding="utf-8").rstrip()
        parts.append(f"\n\n---\n\n<!-- BEGIN {rel} -->\n\n{text}\n\n<!-- END {rel} -->\n")
    out = ROOT / "docs" / "MASTER.md"
    out.write_text("".join(parts), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")

if __name__ == "__main__":
    main()
