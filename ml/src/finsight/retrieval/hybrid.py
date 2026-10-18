from __future__ import annotations

from finsight.interfaces import Hit


def reciprocal_rank_fusion(rankings: list[list[Hit]], k: int = 60, top_n: int | None = None,
                           weights: list[float] | None = None) -> list[Hit]:
    """score(d) = sum over rankings of w_i / (k + rank(d)), rank starting at 1. Default weights are all 1."""
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("one weight per ranking")
    fused: dict[str, float] = {}
    keep: dict[str, Hit] = {}
    for i, ranking in enumerate(rankings):
        w = 1.0 if weights is None else weights[i]
        for rank, hit in enumerate(ranking, start=1):
            fused[hit.chunk.id] = fused.get(hit.chunk.id, 0.0) + w / (k + rank)
            keep.setdefault(hit.chunk.id, hit)
    out = [Hit(keep[i].chunk, s, "rrf") for i, s in fused.items()]
    out.sort(key=lambda h: h.score, reverse=True)
    return out[:top_n] if top_n else out
