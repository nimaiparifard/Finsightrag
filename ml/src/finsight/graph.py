"""The RAG flow wired from config: route -> transform -> retrieve -> (rerank) -> generate -> verify."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from finsight import registry
from finsight.config import Config
from finsight.generation.answer import Answer, build_messages, finalize_answer, generate_answer
from finsight.generation.guardrails import NOT_FOUND
from finsight.interfaces import Embedder, Hit, LLMProvider, Reranker
from finsight.retrieval.hybrid import reciprocal_rank_fusion
from finsight.retrieval.query_transform import transform
from finsight.router import Route, heuristic_route, llm_route
from finsight.store_factory import open_store
from finsight.tracing import tracer


@dataclass
class RetrievalResult:
    hits: list[Hit]
    queries: list[str]
    route: Route
    max_dense_score: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)


@dataclass
class QueryResult:
    answer: Answer
    retrieval: RetrievalResult
    latency_s: float
    usage: dict[str, int]
    cached: bool = False


class RAGPipeline:
    def __init__(self, cfg: Config, store: Any, embedder: Embedder,
                 llm: LLMProvider | None = None, reranker: Reranker | None = None,
                 cache: Any | None = None) -> None:
        self.cfg, self.store, self.embedder = cfg, store, embedder
        self._llm, self._reranker, self.cache = llm, reranker, cache
        self.bm25 = store.keyword_index(cfg.contextual_headers) if cfg.retrieval.mode == "hybrid" else None
        self.companies = store.companies()

    @classmethod
    def from_config(cls, cfg: Config, **overrides: Any) -> RAGPipeline:
        embedder = overrides.get("embedder") or registry.create("embedder", cfg.embedder.name, **cfg.embedder.params)
        store = open_store(cfg, dim=embedder.dim, create=False)
        return cls(cfg, store, embedder, overrides.get("llm"), overrides.get("reranker"),
                   overrides.get("cache"))

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = registry.create("llm", self.cfg.llm.provider, **self.cfg.llm.params)
        return self._llm

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = registry.create("reranker", self.cfg.reranker.name, **self.cfg.reranker.params)
        return self._reranker

    # ---- retrieval -------------------------------------------------------------------------
    def retrieve(self, question: str, filters: dict[str, Any] | None = None) -> RetrievalResult:
        r, t = self.cfg.retrieval, {}
        t0 = time.perf_counter()
        if filters is not None:
            route = Route(filters)
        elif r.use_router:
            route = llm_route(self.llm, question, self.companies)
        else:
            route = heuristic_route(question, self.companies)
        t["route"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        queries = transform(r.query_transform, self.llm if r.query_transform != "none" else None, question)
        t["transform"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        rankings: list[list[Hit]] = []
        max_dense = 0.0
        qvecs = self.embedder.embed(queries, is_query=True)
        for q, qv in zip(queries, qvecs):
            dense = self.store.search(qv, r.dense_k, route.filters)
            if dense:
                max_dense = max(max_dense, dense[0].score)
            rankings.append(dense)
            if self.bm25 is not None:
                rankings.append(self.bm25.search(q, r.bm25_k, route.filters))
        # rankings alternate dense, bm25, dense, bm25 ... (one pair per query variant)
        weights = [1.0, r.bm25_weight] * (len(rankings) // 2) if self.bm25 is not None else None
        fused = rankings[0] if len(rankings) == 1 else reciprocal_rank_fusion(rankings, r.rrf_k, weights=weights)
        t["retrieve"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        if r.rerank:
            hits = self.reranker.rerank(question, fused[: r.dense_k], r.top_k)
        else:
            hits = fused[: r.top_k]
        t["rerank"] = time.perf_counter() - t0
        return RetrievalResult(hits, queries, route, max_dense, t)

    # ---- full flow -------------------------------------------------------------------------
    def query(self, question: str, filters: dict[str, Any] | None = None) -> QueryResult:
        start = time.perf_counter()
        qvec = None
        if self.cache is not None:
            qvec = self.embedder.embed([question], is_query=True)[0]
            hit = self.cache.lookup(filters, qvec)
            if hit is not None:
                ans = Answer(text=hit["text"], citations=hit["citations"], refused=hit["refused"])
                ret = RetrievalResult([], [question], Route(filters or {}))
                return QueryResult(ans, ret, time.perf_counter() - start, {}, cached=True)

        with tracer.trace("finsight.query", question=question) as span:
            before = dict(self.llm.usage)
            ret = self.retrieve(question, filters)
            ms = self.cfg.retrieval.min_score
            if not ret.hits or (ms is not None and ret.max_dense_score < ms) or ret.route.qtype == "out_of_scope":
                ans = Answer(text=NOT_FOUND, refused=True)
            else:
                g = self.cfg.generation
                ans = generate_answer(self.llm, question, ret.hits, prompt=g.prompt, calculator=g.calculator,
                                      guardrails=g.guardrails, token_budget=g.context_token_budget,
                                      temperature=self.cfg.llm.temperature, max_tokens=self.cfg.llm.max_tokens)
            usage = {k: self.llm.usage[k] - before.get(k, 0) for k in self.llm.usage}
            span.update(output=ans.text, metadata={"timings": ret.timings, "usage": usage,
                                                   "prompt_version": ans.prompt_version})
        if self.cache is not None and qvec is not None and not ans.refused:
            self.cache.store(filters, qvec, {"text": ans.text, "citations": ans.citations, "refused": ans.refused})
        return QueryResult(ans, ret, time.perf_counter() - start, usage)

    # ---- streaming (SSE) -------------------------------------------------------------------
    def stream_query(self, question: str, filters: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Yields events: retrieval -> token* -> final. `final` carries the verified answer
        (calculator results filled in, guardrail report), which may differ from the raw tokens."""
        start = time.perf_counter()
        ret = self.retrieve(question, filters)
        yield {"event": "retrieval", "data": {
            "filters": ret.route.filters, "type": ret.route.qtype, "timings": ret.timings,
            "chunks": [{"doc_id": h.chunk.doc_id, "page": h.chunk.page, "score": round(h.score, 4),
                        "type": h.chunk.chunk_type, "section": h.chunk.section,
                        "preview": h.chunk.text[:200]} for h in ret.hits]}}
        ms = self.cfg.retrieval.min_score
        if not ret.hits or (ms is not None and ret.max_dense_score < ms):
            ans = Answer(text=NOT_FOUND, refused=True)
            yield {"event": "token", "data": NOT_FOUND}
        else:
            g = self.cfg.generation
            msgs = build_messages(question, ret.hits, prompt=g.prompt, calculator=g.calculator,
                                  token_budget=g.context_token_budget)
            raw = []
            for tok in self.llm.stream(msgs, temperature=self.cfg.llm.temperature,
                                       max_tokens=self.cfg.llm.max_tokens):
                raw.append(tok)
                yield {"event": "token", "data": tok}
            ans = finalize_answer("".join(raw), ret.hits, prompt=g.prompt, calculator=g.calculator,
                                  guardrails=g.guardrails)
        gr = ans.guardrails
        yield {"event": "final", "data": {
            "answer": ans.text, "citations": ans.citations, "refused": ans.refused,
            "prompt_version": ans.prompt_version, "latency_s": round(time.perf_counter() - start, 3),
            "guardrails": None if gr is None else {
                "ok": gr.ok, "invalid_citations": gr.invalid_citations, "malformed_citations": gr.malformed_citations,
                "no_citations": gr.no_citations,
                "uncited_sentences": gr.uncited_sentences, "ungrounded_numbers": gr.ungrounded_numbers}}}
