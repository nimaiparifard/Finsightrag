from __future__ import annotations

from finsight.config import Config
from finsight.interfaces import Chunker


def get_chunker(cfg: Config) -> Chunker:
    c = cfg.chunker
    if c.name == "recursive":
        from finsight.ingestion.chunkers.recursive import RecursiveChunker

        return RecursiveChunker(c.max_tokens, c.overlap_tokens, cfg.table_chunks)
    if c.name == "section":
        from finsight.ingestion.chunkers.section import SectionChunker

        return SectionChunker(c.max_tokens, c.overlap_tokens, cfg.table_chunks)
    raise ValueError(f"unknown chunker '{c.name}'")
