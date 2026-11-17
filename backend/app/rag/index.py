"""Scheme embedding index (C-02): vectors in a NumPy file, plus a small JSON card saying what was embedded.

The index is stale when the KB file or the embedder changed; a stale or missing index is rebuilt in memory (the KB
is a handful of entries), and the answer says so. `python -m app.rag.build_index` writes it to KB_INDEX_DIR.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.rag import kb as kbmod
from app.rag.embed import Embedder, get_embedder

log = logging.getLogger("sarthi.rag")
VECTORS, CARD = "schemes_vectors.npy", "schemes_index.json"


@dataclass
class Index:
    kb: kbmod.KnowledgeBase
    ids: list[str]
    vectors: np.ndarray
    embedder: Embedder
    kb_sha256: str
    source: str                          # "file" or "built_in_memory"

    def search(self, query: str, k: int | None = None) -> list[tuple[str, float]]:
        q = self.embedder.embed([query], kind="query")[0]
        scores = self.vectors @ q
        order = sorted(range(len(self.ids)), key=lambda i: (-float(scores[i]), self.ids[i]))
        return [(self.ids[i], round(float(scores[i]), 4)) for i in order[:k or len(order)]]

    def similarity(self, query: str) -> dict[str, float]:
        return dict(self.search(query))


def build(kb_path: Path | None = None, embedder: Embedder | None = None) -> Index:
    kb_path = kb_path or kbmod.default_path()
    kb = kbmod.load(kb_path)
    emb = embedder or get_embedder()
    vecs = emb.embed([s.text() for s in kb.schemes], kind="passage")
    return Index(kb, [s.id for s in kb.schemes], vecs, emb, kbmod.file_hash(kb_path), "built_in_memory")


def write(ix: Index, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / VECTORS, ix.vectors)
    card = {"embedder": ix.embedder.name, "dim": int(ix.vectors.shape[1]), "kb_sha256": ix.kb_sha256,
            "ids": ix.ids, "n": len(ix.ids), "test_only": ix.kb.test_only,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds")}
    (out_dir / CARD).write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    return out_dir / CARD


def load(kb_path: Path | None = None, out_dir: Path | None = None, embedder: Embedder | None = None) -> Index:
    """The saved index if it matches the KB file and the embedder, else one built in memory."""
    kb_path = kb_path or kbmod.default_path()
    out_dir = out_dir or Path(get_settings().kb_index_dir)
    emb = embedder or get_embedder()
    kb = kbmod.load(kb_path)
    sha = kbmod.file_hash(kb_path)
    try:
        card = json.loads((out_dir / CARD).read_text(encoding="utf-8"))
        vecs = np.load(out_dir / VECTORS)
        if card["kb_sha256"] == sha and card["embedder"] == emb.name and card["ids"] == [s.id for s in kb.schemes] \
                and vecs.shape == (len(kb.schemes), emb.dim):
            return Index(kb, card["ids"], vecs, emb, sha, "file")
        log.info("scheme index is stale (KB or embedder changed); building in memory")
    except (FileNotFoundError, KeyError, ValueError, OSError):
        log.info("no scheme index file; building in memory")
    return build(kb_path, emb)


_current: dict[tuple, Index] = {}


def current() -> Index:
    """Cached per (KB path, KB hash, embedder). Raises kb.KBMissing / kb.KBInvalid."""
    s = get_settings()
    path = Path(s.kb_path)
    if not path.exists():
        raise kbmod.KBMissing(str(path))
    key = (str(path), kbmod.file_hash(path), s.kb_embedder)
    if key not in _current:
        _current.clear()
        _current[key] = load(path)
    return _current[key]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the scheme embedding index (C-02).")
    ap.add_argument("--kb", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--embedder", choices=["auto", "e5", "fallback"], default=None)
    a = ap.parse_args(argv)
    try:
        ix = build(a.kb, get_embedder(a.embedder))
    except kbmod.KBMissing as e:
        print(f"FAIL {e}: file not found. The team writes it from official pages (checkpoint D-03).")
        return 1
    except kbmod.KBInvalid as e:
        print("FAIL knowledge base is invalid; run make kb-check")
        for m in e.errors:
            print(f"  - {m}")
        return 1
    card = write(ix, a.out or Path(get_settings().kb_index_dir))
    print(f"wrote {card}: {len(ix.ids)} schemes, embedder {ix.embedder.name}"
          + (" (FALLBACK: lexical only, install the EMBED extra for e5)" if ix.embedder.name.startswith("fallback")
             else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
