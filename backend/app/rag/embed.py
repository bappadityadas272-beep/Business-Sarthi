"""Text embedders for the scheme index (C-02, DEC-85).

- `E5Embedder`: `intfloat/multilingual-e5-small` through sentence-transformers. Optional install (build arg
  EMBED=1); the model is downloaded when first used and never committed.
- `HashEmbedder`: a deterministic fallback with no download, made of hashed character n-grams. It only matches
  shared words and spellings, so a Hindi question finds Hindi text but not English text. Every index and every
  answer says which embedder was used.

`KB_EMBEDDER`: `auto` (e5 if sentence-transformers is installed, else fallback), `e5` or `fallback`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import unicodedata

import numpy as np

from app.config import get_settings

FALLBACK_NAME = "fallback-hash-ngram-v1"


class Embedder:
    name = "base"
    dim = 0

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        """Rows are L2-normalised, so a dot product is the cosine similarity. `kind` is query or passage."""
        raise NotImplementedError


class HashEmbedder(Embedder):
    name = FALLBACK_NAME
    dim = 1024
    NGRAMS = (3, 4, 5)

    @staticmethod
    def _norm(text: str) -> str:
        t = unicodedata.normalize("NFKC", text).casefold()
        return " ".join(re.findall(r"\w+", t))

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for word in self._norm(text).split():
            w = f" {word} "
            for n in self.NGRAMS:
                for i in range(max(1, len(w) - n + 1)):
                    h = hashlib.md5(w[i:i + n].encode(), usedforsecurity=False).digest()
                    v[int.from_bytes(h[:4], "little") % self.dim] += 1.0 if h[4] & 1 else -1.0
        norm = float(np.linalg.norm(v))
        return v / norm if norm else v

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), np.float32)


class E5Embedder(Embedder):
    """E5 expects the prefixes "query: " and "passage: "."""

    def __init__(self, model: str | None = None):
        from sentence_transformers import SentenceTransformer  # optional extra (DEC-85)
        self.model_name = model or get_settings().embed_model
        self._m = SentenceTransformer(self.model_name, device="cpu")
        self.name = f"e5:{self.model_name}"
        self.dim = int(self._m.get_sentence_embedding_dimension())

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        prefix = "query: " if kind == "query" else "passage: "
        out = self._m.encode([prefix + t for t in texts], normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(out, dtype=np.float32)


def e5_installed() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


_cache: dict[str, Embedder] = {}


def get_embedder(choice: str | None = None) -> Embedder:
    choice = choice or get_settings().kb_embedder
    if choice == "auto":
        choice = "e5" if e5_installed() else "fallback"
    if choice not in _cache:
        _cache[choice] = E5Embedder() if choice == "e5" else HashEmbedder()
    return _cache[choice]
