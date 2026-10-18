"""LlamaIndex implementation of the same RAG flow, for side-by-side comparison with the plain-Python core.

Two modes:
  * "finsight": LlamaIndex orchestrates (retriever -> response synthesizer) but retrieval is our
    hybrid/rerank pipeline wrapped as a BaseRetriever. Shows the components are framework-agnostic.
  * "native": a stock LlamaIndex VectorStoreIndex built from the same chunks + embeddings
    (dense only, LlamaIndex defaults). This is the honest "LlamaIndex out of the box" baseline.
Both answer through the same prompt rules and the same guardrails, so only retrieval/orchestration differs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from llama_index.core import PromptTemplate, VectorStoreIndex, get_response_synthesizer
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.llms import CompletionResponse, CompletionResponseGen, CustomLLM, LLMMetadata
from llama_index.core.llms.callbacks import llm_completion_callback
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import ResponseMode
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from pydantic import PrivateAttr

from finsight.generation.answer import Answer, finalize_answer
from finsight.generation.guardrails import NOT_FOUND
from finsight.graph import RAGPipeline
from finsight.interfaces import Chunk, Embedder, Hit, LLMProvider, Message

QA_TEMPLATE = PromptTemplate(
    "You are FinSight, a financial filings analyst. Answer ONLY from the CONTEXT, which is extracted from "
    "SEC filings. Each passage starts with its source tag [doc_id:page].\n"
    "Rules: cite every factual sentence with the [doc_id:page] tag; if the context does not contain the "
    f'answer reply exactly "{NOT_FOUND}"; copy numbers exactly with their units; do not do arithmetic '
    "yourself, wrap calculations in <calc>...</calc> using plain numbers and + - * / ( ).\n\n"
    "CONTEXT:\n{context_str}\n\nQUESTION: {query_str}\nANSWER:"
)


class ProviderLLM(CustomLLM):
    """Adapts our LLMProvider protocol to LlamaIndex's LLM interface."""

    _provider: Any = PrivateAttr()

    def __init__(self, provider: LLMProvider, **kw: Any) -> None:
        super().__init__(**kw)
        self._provider = provider

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(context_window=8192, num_output=700, model_name="finsight-provider")

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kw: Any) -> CompletionResponse:
        return CompletionResponse(text=self._provider.generate([Message("user", prompt)]))

    @llm_completion_callback()
    def stream_complete(self, prompt: str, formatted: bool = False, **kw: Any) -> CompletionResponseGen:
        acc = ""
        for tok in self._provider.stream([Message("user", prompt)]):
            acc += tok
            yield CompletionResponse(text=acc, delta=tok)


class EmbedderAdapter(BaseEmbedding):
    _emb: Any = PrivateAttr()

    def __init__(self, embedder: Embedder, **kw: Any) -> None:
        super().__init__(model_name="finsight-embedder", **kw)
        self._emb = embedder

    def _get_query_embedding(self, query: str) -> list[float]:
        return cast(list[float], self._emb.embed([query], is_query=True)[0].tolist())

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return cast(list[float], self._emb.embed([text])[0].tolist())


def _node(h: Hit) -> NodeWithScore:
    c = h.chunk
    node = TextNode(text=f"[{c.doc_id}:{c.page}] {c.text}", id_=c.id,
                    metadata={"doc_id": c.doc_id, "page": c.page, "chunk_type": c.chunk_type,
                              "section": c.section, **{k: v for k, v in c.meta.items() if isinstance(v, str)}})
    return NodeWithScore(node=node, score=h.score)


def _hit(n: NodeWithScore) -> Hit:
    md = n.node.metadata
    text = n.node.get_content().split("] ", 1)[-1]
    meta = {k: v for k, v in md.items() if k not in {"doc_id", "page", "chunk_type", "section"}}
    return Hit(Chunk(md["doc_id"], int(md["page"]), text, md.get("chunk_type", "text"), md.get("section", ""), meta),
               float(n.score or 0.0), "llamaindex")


class FinSightRetriever(BaseRetriever):
    """Our hybrid + rerank retrieval exposed as a LlamaIndex retriever."""

    _pipe: Any = PrivateAttr()
    _filters: Any = PrivateAttr(default=None)

    def __init__(self, pipe: RAGPipeline, filters: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._pipe, self._filters = pipe, filters

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        return [_node(h) for h in self._pipe.retrieve(query_bundle.query_str, self._filters).hits]


class LlamaIndexRAG:
    def __init__(self, retriever: BaseRetriever, llm: LLMProvider, *, guardrails: bool = True) -> None:
        self.retriever, self.llm, self.guardrails = retriever, llm, guardrails
        synth = get_response_synthesizer(llm=ProviderLLM(llm), text_qa_template=QA_TEMPLATE,
                                         response_mode=ResponseMode.COMPACT)
        self.engine = RetrieverQueryEngine(retriever=retriever, response_synthesizer=synth)

    @classmethod
    def from_pipeline(cls, pipe: RAGPipeline, mode: str = "finsight", filters: dict[str, Any] | None = None
                      ) -> LlamaIndexRAG:
        if mode == "finsight":
            retriever: BaseRetriever = FinSightRetriever(pipe, filters)
        elif mode == "native":
            if not hasattr(pipe.store, "vectors"):
                raise ValueError("native mode rebuilds a LlamaIndex index from in-memory vectors; use the numpy store")
            retriever = native_index(pipe.store.chunks, pipe.store.vectors, pipe.embedder).as_retriever(
                similarity_top_k=pipe.cfg.retrieval.top_k)
        else:
            raise ValueError(f"unknown mode '{mode}'")
        return cls(retriever, pipe.llm, guardrails=pipe.cfg.generation.guardrails)

    def query(self, question: str) -> tuple[Answer, list[Hit]]:
        resp = self.engine.query(question)
        hits = [_hit(n) for n in resp.source_nodes]
        return finalize_answer(str(resp), hits, guardrails=self.guardrails), hits


def native_index(chunks: Sequence[Chunk], vectors: Any, embedder: Embedder) -> VectorStoreIndex:
    """Stock LlamaIndex vector index over our chunks; reuses the stored vectors (no re-embedding)."""
    nodes = []
    for c, v in zip(chunks, vectors):
        n = _node(Hit(c, 0.0)).node
        n.embedding = v.tolist()
        nodes.append(n)
    return VectorStoreIndex(nodes, embed_model=EmbedderAdapter(embedder))
