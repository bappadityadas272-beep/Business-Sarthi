#!/usr/bin/env python3
"""Print project status from docs/CHECKPOINTS.md. Use --check to validate (exit 1 on problems)."""
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALID = {"TODO", "IN_PROGRESS", "DONE", "BLOCKED", "DROPPED"}
PRI = {"P0": 0, "P1": 1, "P2": 2}

def parse():
    rows = []
    for line in (ROOT / "docs" / "CHECKPOINTS.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 8 and re.fullmatch(r"[A-Z]-\d{2}", cells[0]):
            rows.append(dict(zip(["id", "title", "feat", "pri", "deps", "status", "acc", "notes"], cells)))
    for r in rows:
        r["deps"] = [] if r["deps"] in ("-", "") else [d.strip() for d in r["deps"].split(",")]
    return rows

def check(rows):
    errs, ids = [], {r["id"] for r in rows}
    if len(ids) != len(rows):
        errs.append("duplicate IDs")
    for r in rows:
        if r["status"] not in VALID: errs.append(f'{r["id"]}: bad status {r["status"]}')
        if r["pri"] not in PRI: errs.append(f'{r["id"]}: bad priority {r["pri"]}')
        if not r["acc"]: errs.append(f'{r["id"]}: empty acceptance')
        for d in r["deps"]:
            if d not in ids: errs.append(f'{r["id"]}: unknown dependency {d}')
    graph = {r["id"]: r["deps"] for r in rows}
    state = {}
    def dfs(n, path):
        if state.get(n) == 1: errs.append("cycle: " + " -> ".join(path + [n])); return
        if state.get(n) == 2: return
        state[n] = 1
        for d in graph.get(n, []):
            if d in graph: dfs(d, path + [n])
        state[n] = 2
    for n in graph: dfs(n, [])
    return errs

def main():
    rows = parse()
    errs = check(rows)
    if "--check" in sys.argv:
        print(f"{len(rows)} checkpoints parsed")
        for e in errs: print("ERROR:", e)
        sys.exit(1 if errs else 0)
    done = {r["id"] for r in rows if r["status"] == "DONE"}
    c = Counter(r["status"] for r in rows)
    print(f"Checkpoints: {len(rows)} | " + " | ".join(f"{k} {c.get(k,0)}" for k in sorted(VALID)))
    p0 = [r for r in rows if r["pri"] == "P0"]
    print(f"P0 done: {sum(r['id'] in done for r in p0)}/{len(p0)}")
    for grp in "SDBMCFQR":
        g = [r for r in rows if r["id"][0] == grp]
        print(f"  {grp}: {sum(r['id'] in done for r in g)}/{len(g)}")
    nxt = [r for r in rows if r["status"] == "TODO" and all(d in done for d in r["deps"])]
    nxt.sort(key=lambda r: (PRI[r["pri"]], r["id"]))
    print("\nNext available (dependencies met):")
    for r in nxt[:5]: print(f'  {r["id"]} [{r["pri"]}] {r["title"]}')
    for r in rows:
        if r["status"] in ("IN_PROGRESS", "BLOCKED"): print(f'\n{r["status"]}: {r["id"]} {r["title"]} {r["notes"]}')
    if errs: print("\nWarnings:", *errs, sep="\n  ")

if __name__ == "__main__":
    main()
