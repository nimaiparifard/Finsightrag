# ADR 0001: Django for the product, FastAPI for serving, a framework-free ML package

**Status:** accepted

## Context

The system has two very different jobs: product logic (users, JWT, filings, conversations, feedback, background
ingestion, admin) and low-latency model serving (retrieval + generation, streaming tokens).

## Decision

* **Django + DRF** owns users, data and jobs. Its admin, ORM migrations, permissions and Celery integration are the
  mature answer to that half of the problem.
* **FastAPI** owns serving. It is async-friendly, has first-class streaming responses (SSE) and pydantic schemas, and
  can be scaled and deployed independently of the web app.
* **The `finsight` package contains the actual RAG logic and imports neither.** Both services (and the CLI, tests and
  notebooks) call it.

## Consequences

* (+) The RAG core is testable with a fake LLM and a hash embedder, no web stack required.
* (+) Serving can be scaled (and given a GPU) separately from the CPU-only web workers.
* (−) Two services means an HTTP hop. Django wraps it in a client with timeouts, bounded retries and typed errors, and
  proxies the SSE stream so the browser only ever talks to Django.
* (−) The index lives where serving can read it (shared volume or Postgres). After ingestion the worker calls
  serving's `/v1/admin/reload`, which swaps the pipeline without a restart.
