from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

import numpy as np

from finsight.registry import register


@register("embedder", "sentence_transformers")
class SentenceTransformerEmbedder:
    # bge models want this prefix on queries only
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model: str = "BAAI/bge-base-en-v1.5", device: str | None = None,
                 batch_size: int = 64, query_prefix: bool | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model, device=device)
        self.model.max_seq_length = min(self.model.max_seq_length or 512, 512)
        self.dim = int(self.model.get_sentence_embedding_dimension() or 0)
        self.batch_size = batch_size
        self.use_prefix = ("bge" in model.lower() and "m3" not in model.lower()) if query_prefix is None else query_prefix

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
        if is_query and self.use_prefix:
            texts = [self.QUERY_PREFIX + t for t in texts]
        vecs = self.model.encode(list(texts), batch_size=self.batch_size, normalize_embeddings=True,
                                 show_progress_bar=len(texts) > 256)
        return np.asarray(vecs, dtype=np.float32)


@register("embedder", "hash")
class HashEmbedder:
    """Deterministic bag-of-words feature hashing. Tiny, offline: used in tests/CI."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return np.asarray(out / np.maximum(norms, 1e-9), dtype=np.float32)
