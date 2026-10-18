# API

Interactive docs: `/api/docs/` (Swagger) and `/api/schema/` (OpenAPI). All endpoints except `/api/health/`,
`/api/auth/register/` and `/api/auth/token/` need `Authorization: Bearer <access token>`. Errors look like
`{"error": {"code": "...", "message": ...}}`.

## Auth

| Method | Path | |
|---|---|---|
| POST | `/api/auth/register/` | `{email, password}` (min 8 chars, Django password validators apply) |
| POST | `/api/auth/token/` | → `{access, refresh}`; access lives 15 min, refresh 7 days and rotates |
| POST | `/api/auth/token/refresh/` | `{refresh}` |
| GET | `/api/auth/me/` | |

## Filings

| Method | Path | |
|---|---|---|
| POST | `/api/filings/ingest/` | `{ticker, years: [from, to], forms: ["10-K","10-Q"]}` → `202` + job (rate limited) |
| GET | `/api/ingestion-jobs/{id}/` | `status`, `done/total/failed`, `progress` (0-100) |
| GET | `/api/companies/`, `/api/filings/?ticker=AAPL&form=10-K&status=indexed` | |
| GET | `/api/documents/{doc_id}/file/` | the source PDF/HTML (HTML is served sandboxed with a strict CSP) |
| GET | `/api/documents/{doc_id}/pages/{n}/` | text + tables of one page (0-indexed) |

## Chat

| Method | Path | |
|---|---|---|
| POST | `/api/chat/conversations/` | `{title?, filters?}` |
| GET | `/api/chat/conversations/{id}/` | with messages |
| POST | `/api/chat/conversations/{id}/messages/` | `{question, company?, year?, form?, stream?}` (rate limited) |
| POST | `/api/chat/messages/{id}/feedback/` | `{thumbs_up, comment?}` |
| POST | `/api/chat/compare/` | agentic comparison, stateless |

### Streaming

With `"stream": true` the response is `text/event-stream`:

```
event: retrieval   data: {"filters":…, "chunks":[{doc_id,page,score,type,section,preview}], "timings":…}
event: token       data: <text fragment>        (repeated)
event: final       data: {"answer", "citations":[{doc_id,page}], "refused", "guardrails":{ok,…}, "latency_s"}
event: saved       data: {"message_id": "…"}    (use it for feedback)
event: error       data: {"code","message"}     (only on failure)
```

`token` events are the raw model output; `final.answer` is authoritative (calculator results filled in and
guardrails applied), so the UI should replace the streamed text with it.

## Evaluation

| Method | Path | |
|---|---|---|
| GET | `/api/evaluation/runs/` | imported eval runs (`config_name`, `metrics`, …) |
| POST | `/api/evaluation/runs/refresh/` | admin only: import new result files |

## Serving (internal)

`POST /v1/query` (SSE or JSON), `/v1/retrieve` (debug), `/v1/compare`, `/v1/admin/reload` (optional
`X-Admin-Token`), `GET /health`, `GET /metrics`.
