from __future__ import annotations

import math
from collections.abc import Sequence

from finsight.interfaces import Hit

Evidence = tuple[str, int]  # (doc_id, page)


def _pages(hits: Sequence[Hit]) -> list[Evidence]:
    """Rank-ordered unique (doc_id, page) pairs; several chunks from one page count once."""
    return list(dict.fromkeys((h.chunk.doc_id, h.chunk.page) for h in hits))


def recall_at_k(hits: Sequence[Hit], gold: set[Evidence], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(_pages(hits)[:k]) & gold) / len(gold)


def hit_at_k(hits: Sequence[Hit], gold: set[Evidence], k: int) -> float:
    return float(bool(set(_pages(hits)[:k]) & gold))


def mrr(hits: Sequence[Hit], gold: set[Evidence]) -> float:
    for rank, p in enumerate(_pages(hits), start=1):
        if p in gold:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(hits: Sequence[Hit], gold: set[Evidence], k: int) -> float:
    ranked = _pages(hits)[:k]
    dcg = sum(1.0 / math.log2(i + 2) for i, p in enumerate(ranked) if p in gold)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0
