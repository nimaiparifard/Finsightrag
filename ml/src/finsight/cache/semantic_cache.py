"""Semantic cache: a query hits if its embedding is within cosine > threshold of a cached query
AND the filters match. In-memory by default; RedisSemanticCache shares it across workers."""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np


def _fkey(filters: dict[str, Any] | None) -> str:
    return json.dumps(filters or {}, sort_keys=True, default=str)


class InMemorySemanticCache:
    def __init__(self, threshold: float = 0.95, ttl_s: float | None = None, max_entries: int = 1000) -> None:
        self.threshold, self.ttl, self.max = threshold, ttl_s, max_entries
        self._entries: list[tuple[str, np.ndarray, Any, float]] = []
        self.hits = self.misses = 0

    def get(self, key: str, vector: np.ndarray | None = None) -> Any | None:
        """key = filters key (see lookup()); vector = normalized query embedding."""
        now = time.time()
        if self.ttl:
            self._entries = [e for e in self._entries if now - e[3] < self.ttl]
        best, best_sim = None, self.threshold
        for k, v, value, _ in self._entries:
            if k != key or vector is None:
                continue
            sim = float(v @ vector)
            if sim >= best_sim:
                best, best_sim = value, sim
        self.hits += best is not None
        self.misses += best is None
        return best

    def set(self, key: str, value: Any, vector: np.ndarray | None = None) -> None:
        if vector is None:
            return
        self._entries.append((key, vector.astype(np.float32), value, time.time()))
        self._entries = self._entries[-self.max :]

    # convenience wrappers that build the key from filters
    def lookup(self, filters: dict[str, Any] | None, vector: np.ndarray) -> Any | None:
        return self.get(_fkey(filters), vector)

    def store(self, filters: dict[str, Any] | None, vector: np.ndarray, value: Any) -> None:
        self.set(_fkey(filters), value, vector)


class RedisSemanticCache(InMemorySemanticCache):
    """Entries live in a Redis hash, so every worker sees them. Search is a linear scan of the
    (small, bounded) entry set, which is plenty for a cache of a few thousand questions."""

    def __init__(self, url: str = "redis://localhost:6379/0", namespace: str = "finsight:cache",
                 **kw: Any) -> None:
        super().__init__(**kw)
        import redis

        self.r = redis.Redis.from_url(url)
        self.ns = namespace

    def _load(self) -> None:
        self._entries = []
        for _, raw in self.r.hgetall(self.ns).items():
            d = json.loads(raw)
            self._entries.append((d["k"], np.asarray(d["v"], dtype=np.float32), d["value"], d["t"]))

    def get(self, key: str, vector: np.ndarray | None = None) -> Any | None:
        self._load()
        return super().get(key, vector)

    def set(self, key: str, value: Any, vector: np.ndarray | None = None) -> None:
        if vector is None:
            return
        entry_id = f"{abs(hash((key, vector.tobytes()))):x}"
        self.r.hset(self.ns, entry_id, json.dumps(
            {"k": key, "v": vector.astype(float).tolist(), "value": value, "t": time.time()}))
        if self.ttl:
            self.r.expire(self.ns, int(self.ttl))
