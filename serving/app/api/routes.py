from __future__ import annotations

import hmac
import json
import os
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import metrics as m
from app.deps import get_pipeline
from app.schemas import QueryRequest, QueryResponse, RetrieveResponse
from finsight.graph import RAGPipeline

router = APIRouter()


def _chunks(hits: list[Any]) -> list[dict[str, Any]]:
    return [{"doc_id": h.chunk.doc_id, "page": h.chunk.page, "score": round(h.score, 4),
             "type": h.chunk.chunk_type, "section": h.chunk.section, "preview": h.chunk.text[:200]}
            for h in hits]


@router.get("/health")
def health(pipe: RAGPipeline = Depends(get_pipeline)) -> dict[str, Any]:
    return {"status": "ok", "config": pipe.cfg.name, "chunks": pipe.store.count(),
            "documents": len(pipe.store.doc_ids())}


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def require_admin(request: Request) -> None:
    """If SERVING_ADMIN_TOKEN is set, admin endpoints need `X-Admin-Token`. Serving is meant to sit on a
    private network, so this is defence in depth rather than the only barrier."""
    token = os.environ.get("SERVING_ADMIN_TOKEN")
    if token and not hmac.compare_digest(request.headers.get("x-admin-token", ""), token):
        raise HTTPException(403, "admin token required")


@router.post("/v1/admin/reload", dependencies=[Depends(require_admin)])
def reload_index(request: Request) -> dict[str, Any]:
    """Rebuild the pipeline from disk after ingestion added filings. The old pipeline serves until the swap."""
    new = request.app.state.factory()
    request.app.state.pipeline = new
    return {"status": "reloaded", "chunks": new.store.count(), "documents": len(new.store.doc_ids())}


@router.post("/v1/compare", response_model=QueryResponse)
def compare(req: QueryRequest, pipe: RAGPipeline = Depends(get_pipeline)) -> QueryResponse:
    """Agentic mode: decompose a comparison into sub-questions, answer each, synthesize."""
    try:
        from finsight.integrations.langgraph_agent import ComparisonAgent
    except ImportError as e:  # langgraph is an optional extra
        raise HTTPException(501, "comparison agent not installed (pip install langgraph)") from e
    t0 = time.perf_counter()
    out = ComparisonAgent(pipe).run(req.question)
    ans = out["answer"]
    _observe("compare", pipe, t0, ans.refused, False, {}, ans.guardrails)
    gr = ans.guardrails
    return QueryResponse(answer=ans.text, citations=ans.citations, refused=ans.refused,
                         latency_s=round(time.perf_counter() - t0, 3), guardrails_ok=None if gr is None else gr.ok,
                         prompt_version=ans.prompt_version, chunks=_chunks(out.get("hits", [])[:12]))


@router.post("/v1/retrieve", response_model=RetrieveResponse)
def retrieve(req: QueryRequest, pipe: RAGPipeline = Depends(get_pipeline)) -> dict[str, Any]:
    ret = pipe.retrieve(req.question, req.filters())
    return {"filters": ret.route.filters, "type": ret.route.qtype, "timings": ret.timings,
            "chunks": _chunks(ret.hits)}


@router.post("/v1/query")
def query(req: QueryRequest, pipe: RAGPipeline = Depends(get_pipeline)):  # type: ignore[no-untyped-def]
    if req.stream:
        return StreamingResponse(_sse(pipe, req), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    t0 = time.perf_counter()
    res = pipe.query(req.question, req.filters())
    _observe("query", pipe, t0, res.answer.refused, res.cached, res.usage, res.answer.guardrails)
    gr = res.answer.guardrails
    return QueryResponse(
        answer=res.answer.text, citations=res.answer.citations, refused=res.answer.refused,
        cached=res.cached, latency_s=round(res.latency_s, 3), guardrails_ok=None if gr is None else gr.ok,
        prompt_version=res.answer.prompt_version, chunks=_chunks(res.retrieval.hits), usage=res.usage)


def _sse(pipe: RAGPipeline, req: QueryRequest) -> Iterator[str]:
    t0 = time.perf_counter()
    refused, gr = False, None
    for ev in pipe.stream_query(req.question, req.filters()):
        if ev["event"] == "final":
            refused = ev["data"]["refused"]
            gr = ev["data"]["guardrails"]
        data = ev["data"] if isinstance(ev["data"], str) else json.dumps(ev["data"])
        # SSE: a payload containing newlines needs one "data:" line per line
        body = "\n".join(f"data: {line}" for line in data.split("\n"))
        yield f"event: {ev['event']}\n{body}\n\n"
    m.REQUESTS.labels("query_stream", "ok", pipe.cfg.name).inc()
    m.LATENCY.labels("query_stream").observe(time.perf_counter() - t0)
    if refused:
        m.REFUSALS.inc()
    if gr is not None and not gr["ok"]:
        m.GUARDRAIL_FAIL.inc()


def _observe(endpoint: str, pipe: RAGPipeline, t0: float, refused: bool, cached: bool,
             usage: dict[str, int], gr: Any) -> None:
    m.REQUESTS.labels(endpoint, "ok", pipe.cfg.name).inc()
    m.LATENCY.labels(endpoint).observe(time.perf_counter() - t0)
    if refused:
        m.REFUSALS.inc()
    if cached:
        m.CACHE_HITS.inc()
    for k, v in usage.items():
        m.TOKENS.labels(k).inc(v)
    if gr is not None and not gr.ok:
        m.GUARDRAIL_FAIL.inc()
