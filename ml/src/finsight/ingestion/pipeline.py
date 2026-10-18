"""ingest(): parse -> chunk -> embed -> index. Idempotent: documents already indexed are skipped."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from finsight.config import Config
from finsight.ingestion.chunkers import get_chunker
from finsight.ingestion.parsers import get_parser
from finsight.interfaces import Embedder, Page, ParsedDocument, Table
from finsight.store_factory import index_path, open_store  # noqa: F401  (index_path re-exported)

log = logging.getLogger("finsight.ingest")


def parser_for(path: str, default: str) -> str:
    """Pick the parser from the file type, so one index can mix PDF and EDGAR HTML filings."""
    suffix = Path(path).suffix.lower()
    return "html" if suffix in {".htm", ".html"} else "pdf" if suffix == ".pdf" else default


def load_or_parse(cfg: Config, doc_id: str, path: str, meta: dict[str, Any] | None = None) -> ParsedDocument:
    kind = parser_for(path, cfg.parser.name)
    cache = Path(cfg.parsed_dir) / kind / f"{doc_id}.json"
    if cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8"))
        pages = [Page(p["doc_id"], p["page"], p["text"], [Table(**t) for t in p["tables"]]) for p in raw["pages"]]
        doc = ParsedDocument(raw["doc_id"], pages, raw["meta"])
    else:
        doc = get_parser(kind, cfg.parser.extract_tables).parse(path, doc_id)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(asdict(doc)), encoding="utf-8")
    doc.meta.update(meta or {})
    return doc


def ingest(cfg: Config, docs: dict[str, str], embedder: Embedder,
           progress: Callable[[int, int, str], None] | None = None,
           meta: dict[str, dict[str, Any]] | None = None, llm: Any = None) -> Any:
    """docs: {doc_id: file path}; meta: optional {doc_id: extra chunk metadata} (company, ticker, ...).
    Returns the (saved) store."""
    store = open_store(cfg, dim=embedder.dim)
    have = store.doc_ids()
    chunker = get_chunker(cfg)
    todo = [(d, p) for d, p in docs.items() if d not in have]
    for n, (doc_id, file) in enumerate(todo, start=1):
        if progress:
            progress(n, len(todo), doc_id)
        try:
            chunks = chunker.chunk(load_or_parse(cfg, doc_id, file, (meta or {}).get(doc_id)))
        except Exception as e:  # one bad PDF must not kill the batch
            log.warning("skipping %s: %s", doc_id, e)
            continue
        if not chunks:
            continue
        if cfg.table_summaries.enabled:
            if llm is None:
                raise ValueError("table_summaries.enabled needs an llm: ingest(..., llm=provider)")
            from finsight.ingestion.table_summaries import summarize_tables

            summarize_tables(chunks, llm, cache_path=Path(cfg.parsed_dir) / "table_summaries" / f"{doc_id}.json",
                             min_rows=cfg.table_summaries.min_rows, max_per_doc=cfg.table_summaries.max_per_doc)
        vectors = embedder.embed([c.embed_text(cfg.contextual_headers) for c in chunks])
        store.upsert(chunks, vectors)
    if todo:
        store.save(str(index_path(cfg)))
    return store
