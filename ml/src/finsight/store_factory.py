"""Open the configured vector store (numpy on disk, or Postgres + pgvector)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from finsight.config import Config
from finsight.stores import NumpyVectorStore


def index_path(cfg: Config) -> Path:
    return Path(cfg.index_dir) / cfg.index_key()


def open_store(cfg: Config, dim: int | None = None, *, create: bool = True, version: int | None = None) -> Any:
    """create=False (serving): numpy requires an existing index. dim is needed for a new pgvector table."""
    if cfg.store.backend == "pgvector":
        from finsight.pg_store import PgVectorStore

        dsn = os.environ.get(cfg.store.dsn_env)
        if not dsn:
            raise RuntimeError(f"pgvector backend needs ${cfg.store.dsn_env} (a Postgres DSN)")
        if dim is None:
            raise ValueError("pgvector needs the embedding dimension")
        return PgVectorStore(dsn, dim, table=f"finsight_{cfg.index_key()}", version=version)
    path = index_path(cfg)
    if (path / "chunks.jsonl").exists():
        return NumpyVectorStore.load(str(path))
    if not create:
        raise FileNotFoundError(f"no index at {path}; run `finsight ingest` first")
    return NumpyVectorStore()
