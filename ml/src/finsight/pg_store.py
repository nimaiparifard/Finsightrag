"""Postgres backend: pgvector for dense search, Postgres full-text search for the keyword side.

Index versioning: every row carries `index_version`; a single-row table `finsight_index_meta` says which version
is active. Re-index into version N+1 while N keeps serving, then `activate(N+1)` flips the alias in one statement
(zero-downtime), and old versions can be dropped afterwards.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

import numpy as np

from finsight.interfaces import Chunk, Hit

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_WORD = re.compile(r"[A-Za-z0-9]+")


def _vec(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v.astype(np.float32)) + "]"


def _row_to_chunk(r: tuple[Any, ...]) -> Chunk:
    doc_id, page, ctype, section, text, meta = r
    return Chunk(doc_id, page, text, ctype, section or "", meta if isinstance(meta, dict) else json.loads(meta))


def _where(filters: dict[str, Any] | None, version_param: str = "%s") -> tuple[str, list[Any]]:
    """Case-insensitive match on metadata keys, mirroring stores.matches()."""
    clauses, params = [f"index_version = {version_param}"], []
    for key, want in (filters or {}).items():
        wants = [str(w).lower() for w in (want if isinstance(want, (list, tuple, set)) else [want])]
        if key == "doc_id":
            clauses.append("lower(doc_id) = ANY(%s)")
        else:
            if not _IDENT.match(key):
                raise ValueError(f"bad filter key '{key}'")
            clauses.append(f"lower(meta->>'{key}') = ANY(%s)")
        params.append(wants)
    return " AND ".join(clauses), params


class PgVectorStore:
    def __init__(self, dsn: str, dim: int, table: str = "finsight_chunks", version: int | None = None) -> None:
        import psycopg

        if not _IDENT.match(table):
            raise ValueError("bad table name")
        self.dsn, self.dim, self.table = dsn, dim, table
        self.conn = psycopg.connect(dsn, autocommit=True)
        self._create_schema()
        self.version = version if version is not None else self.active_version()

    # ---- schema / versioning -----------------------------------------------------------------
    def _create_schema(self) -> None:
        t = self.table
        with self.conn.cursor() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector")
            c.execute(f"""CREATE TABLE IF NOT EXISTS {t} (
                index_version int NOT NULL, id text NOT NULL, doc_id text NOT NULL, page int NOT NULL,
                chunk_type text NOT NULL, section text NOT NULL DEFAULT '', text text NOT NULL,
                meta jsonb NOT NULL DEFAULT '{{}}', embedding vector({self.dim}) NOT NULL,
                tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
                PRIMARY KEY (index_version, id))""")
            c.execute(f"CREATE INDEX IF NOT EXISTS {t}_hnsw ON {t} USING hnsw (embedding vector_cosine_ops)")
            c.execute(f"CREATE INDEX IF NOT EXISTS {t}_tsv ON {t} USING gin (tsv)")
            c.execute(f"CREATE INDEX IF NOT EXISTS {t}_doc ON {t} (index_version, doc_id)")
            c.execute(f"CREATE TABLE IF NOT EXISTS {t}_meta (singleton bool PRIMARY KEY DEFAULT true CHECK (singleton), "
                      "active_version int NOT NULL)")
            c.execute(f"INSERT INTO {t}_meta (singleton, active_version) VALUES (true, 1) ON CONFLICT DO NOTHING")

    def active_version(self) -> int:
        with self.conn.cursor() as c:
            c.execute(f"SELECT active_version FROM {self.table}_meta")
            return int(c.fetchone()[0])  # type: ignore[index]

    def activate(self, version: int) -> None:
        """Atomically point readers at `version`. Fails if that version has no rows (guards typos)."""
        with self.conn.transaction(), self.conn.cursor() as c:
            c.execute(f"SELECT count(*) FROM {self.table} WHERE index_version = %s", (version,))
            if c.fetchone()[0] == 0:  # type: ignore[index]
                raise ValueError(f"index version {version} is empty")
            c.execute(f"UPDATE {self.table}_meta SET active_version = %s", (version,))

    def drop_version(self, version: int) -> int:
        if version == self.active_version():
            raise ValueError("refusing to drop the active index version")
        with self.conn.cursor() as c:
            c.execute(f"DELETE FROM {self.table} WHERE index_version = %s", (version,))
            return c.rowcount

    # ---- VectorStore protocol ----------------------------------------------------------------
    def upsert(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None:
        rows = [(self.version, c.id, c.doc_id, c.page, c.chunk_type, c.section, c.text, json.dumps(c.meta), _vec(v))
                for c, v in zip(chunks, vectors)]
        with self.conn.transaction(), self.conn.cursor() as c:
            c.executemany(
                f"INSERT INTO {self.table} (index_version, id, doc_id, page, chunk_type, section, text, meta, embedding) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector) ON CONFLICT (index_version, id) DO NOTHING", rows)

    def search(self, vector: np.ndarray, k: int, filters: dict[str, Any] | None = None) -> list[Hit]:
        where, params = _where(filters)
        q = _vec(vector)
        with self.conn.cursor() as c:
            c.execute(f"SELECT doc_id, page, chunk_type, section, text, meta, 1 - (embedding <=> %s::vector) AS score "
                      f"FROM {self.table} WHERE {where} ORDER BY embedding <=> %s::vector LIMIT %s",
                      [q, self.version, *params, q, k])
            return [Hit(_row_to_chunk(r[:6]), float(r[6]), "dense") for r in c.fetchall()]

    def save(self, path: str) -> None:  # writes are immediate; kept for protocol parity with NumpyVectorStore
        return None

    # ---- extras the pipeline uses ------------------------------------------------------------
    def doc_ids(self) -> set[str]:
        with self.conn.cursor() as c:
            c.execute(f"SELECT DISTINCT doc_id FROM {self.table} WHERE index_version = %s", (self.version,))
            return {r[0] for r in c.fetchall()}

    def companies(self) -> set[str]:
        with self.conn.cursor() as c:
            c.execute(f"SELECT DISTINCT meta->>'company' FROM {self.table} WHERE index_version = %s", (self.version,))
            return {r[0] for r in c.fetchall() if r[0]}

    def count(self) -> int:
        with self.conn.cursor() as c:
            c.execute(f"SELECT count(*) FROM {self.table} WHERE index_version = %s", (self.version,))
            return int(c.fetchone()[0])  # type: ignore[index]

    def keyword_index(self, contextual_headers: bool = False) -> PgKeywordIndex:
        return PgKeywordIndex(self)

    def close(self) -> None:
        self.conn.close()


class PgKeywordIndex:
    """Postgres FTS: OR-of-terms tsquery ranked with ts_rank_cd (cover density, rewards nearby terms)."""

    def __init__(self, store: PgVectorStore) -> None:
        self.store = store

    def build(self, chunks: Sequence[Chunk]) -> None:  # the tsvector column is maintained by Postgres itself
        return None

    def search(self, query: str, k: int, filters: dict[str, Any] | None = None) -> list[Hit]:
        words = list(dict.fromkeys(w.lower() for w in _WORD.findall(query)))[:40]
        if not words:
            return []
        tsq = " | ".join(words)  # alnum only, so injection into tsquery syntax is impossible
        where, params = _where(filters)
        s = self.store
        with s.conn.cursor() as c:
            c.execute(f"SELECT doc_id, page, chunk_type, section, text, meta, ts_rank_cd(tsv, q) AS score "
                      f"FROM {s.table}, to_tsquery('english', %s) q WHERE {where} AND tsv @@ q "
                      f"ORDER BY score DESC LIMIT %s", [tsq, s.version, *params, k])
            return [Hit(_row_to_chunk(r[:6]), float(r[6]), "bm25") for r in c.fetchall()]
