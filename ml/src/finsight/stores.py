"""Vector store + BM25 index. The on-disk format is one directory: chunks.jsonl + vectors.npy."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from finsight.interfaces import Chunk, Hit

_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def matches(chunk: Chunk, filters: dict[str, Any] | None) -> bool:
    """filters: {'company': 'Apple' | ['Apple', ...], 'year': '2023', 'doc_id': ..., 'form': ...}"""
    if not filters:
        return True
    for key, want in filters.items():
        have = chunk.doc_id if key == "doc_id" else chunk.meta.get(key)
        wants = want if isinstance(want, (list, tuple, set)) else [want]
        if str(have).lower() not in {str(w).lower() for w in wants}:
            return False
    return True


class NumpyVectorStore:
    """Exact cosine search over normalized vectors. Fine to ~1M chunks; pgvector backs the web app."""

    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self._ids: set[str] = set()

    def upsert(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None:
        keep = [i for i, c in enumerate(chunks) if c.id not in self._ids]  # dedup
        if not keep:
            return
        new = vectors[keep].astype(np.float32)
        self.vectors = new if not len(self.chunks) else np.vstack([self.vectors, new])
        for i in keep:
            self.chunks.append(chunks[i])
            self._ids.add(chunks[i].id)

    def search(self, vector: np.ndarray, k: int, filters: dict[str, Any] | None = None) -> list[Hit]:
        if not self.chunks:
            return []
        scores = self.vectors @ vector.astype(np.float32)
        if filters:
            mask = np.array([matches(c, filters) for c in self.chunks])
            scores = np.where(mask, scores, -np.inf)
        k = min(k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [Hit(self.chunks[i], float(scores[i]), "dense") for i in top if np.isfinite(scores[i])]

    def save(self, path: str) -> None:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        np.save(p / "vectors.npy", self.vectors)
        with open(p / "chunks.jsonl", "w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps(asdict(c)) + "\n")

    @classmethod
    def load(cls, path: str) -> NumpyVectorStore:
        p = Path(path)
        store = cls()
        store.vectors = np.load(p / "vectors.npy")
        with open(p / "chunks.jsonl", encoding="utf-8") as f:
            store.chunks = [Chunk(**json.loads(line)) for line in f]
        store._ids = {c.id for c in store.chunks}
        return store

    def doc_ids(self) -> set[str]:
        return {c.doc_id for c in self.chunks}

    def companies(self) -> set[str]:
        return {str(c.meta["company"]) for c in self.chunks if c.meta.get("company")}

    def count(self) -> int:
        return len(self.chunks)

    def keyword_index(self, contextual_headers: bool = False) -> BM25Index:
        idx = BM25Index()
        idx.build(self.chunks, contextual_headers)
        return idx


class BM25Index:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._bm25: BM25Okapi | None = None

    def build(self, chunks: Sequence[Chunk], contextual_headers: bool = False) -> None:
        self.chunks = list(chunks)
        corpus = [tokenize(c.embed_text(contextual_headers)) or ["_"] for c in self.chunks]
        self._bm25 = BM25Okapi(corpus)

    def search(self, query: str, k: int, filters: dict[str, Any] | None = None) -> list[Hit]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        if filters:
            mask = np.array([matches(c, filters) for c in self.chunks])
            scores = np.where(mask, scores, -np.inf)
        k = min(k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [Hit(self.chunks[i], float(scores[i]), "bm25") for i in top if scores[i] > 0]
