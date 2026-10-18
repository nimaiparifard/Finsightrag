from __future__ import annotations

from finsight.interfaces import Hit
from finsight.registry import register


@register("reranker", "cross_encoder")
class CrossEncoderReranker:
    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3", device: str | None = None,
                 batch_size: int = 16, max_length: int = 512) -> None:
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model, device=device, max_length=max_length)
        self.batch_size = batch_size

    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        if not hits:
            return []
        scores = self.model.predict([(query, h.chunk.embed_text(True)) for h in hits],
                                    batch_size=self.batch_size, show_progress_bar=False)
        ranked = sorted(zip(hits, scores), key=lambda x: float(x[1]), reverse=True)[:top_k]
        return [Hit(h.chunk, float(s), "rerank") for h, s in ranked]


@register("reranker", "identity")
class IdentityReranker:
    """No-op reranker for tests."""

    def __init__(self, **_: object) -> None: ...

    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        return hits[:top_k]
