# ADR 0003: Two vector-store backends

**Status:** accepted

## Context

Research runs (ablations over 21k chunks) want a zero-setup, exact, easy-to-reset index. The web app wants a
shared, concurrent, transactional one.

## Decision

* `NumpyVectorStore` (default): exact cosine search, a `chunks.jsonl` + `vectors.npy` directory per ingestion
  configuration, BM25 via `rank_bm25`. No services needed, so unit tests, CI and the ablations use it.
* `PgVectorStore` (`store.backend: pgvector`): HNSW index for dense search, Postgres full-text search for the keyword
  side, an `index_version` column and an atomic active-version switch.

Both expose the same methods (`upsert`, `search`, `doc_ids`, `companies`, `count`, `keyword_index`), so the pipeline
does not know which it has.

## Consequences

* The two keyword scorers differ (BM25 vs `ts_rank_cd`), so hybrid numbers are not directly comparable across
  backends. Compare configs within one backend.
* The pgvector table name includes the ingestion-config hash, so changing the embedder or chunker never mixes
  incompatible vectors into one table.
