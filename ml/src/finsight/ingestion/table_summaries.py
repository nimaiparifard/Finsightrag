"""Table summary indexing: one LLM-written paragraph per table, used for retrieval only."""

from __future__ import annotations

import json
from pathlib import Path

from finsight.interfaces import Chunk, LLMProvider, Message

SYSTEM = (
    "You index financial tables for search. Write ONE short paragraph (max 80 words) describing what the table "
    "contains: the statement or topic, the line items, the periods/years and the units. Include the most important "
    "figures. Do not invent anything that is not in the table. Reply with the paragraph only."
)


def summarize_tables(chunks: list[Chunk], llm: LLMProvider, *, cache_path: Path | None = None, min_rows: int = 3,
                     max_per_doc: int = 400) -> int:
    """Adds meta['summary'] to table chunks in place. Cached on disk by chunk id, so re-ingesting is free and a
    crash halfway loses nothing. Returns the number of LLM calls made."""
    cache: dict[str, str] = {}
    if cache_path and cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    calls = done = 0
    for c in chunks:
        if c.chunk_type != "table" or c.text.count("\n") + 1 < min_rows or done >= max_per_doc:
            continue
        done += 1
        if c.id in cache:
            c.meta["summary"] = cache[c.id]
            continue
        header = c.header()
        ctx = f"Filing: {header}\n" if header else ""
        try:
            out = llm.generate([Message("system", SYSTEM), Message("user", f"{ctx}Table:\n{c.text[:3500]}")],
                               temperature=0.0, max_tokens=160).strip()
        except Exception:  # a failed summary must never fail ingestion: the raw table is still indexed
            continue
        calls += 1
        if out:
            cache[c.id] = c.meta["summary"] = out
    if cache_path and calls:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return calls
