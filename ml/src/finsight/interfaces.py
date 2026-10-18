"""Core types and the Protocols every pluggable component implements."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass
class Table:
    page: int
    markdown: str
    rows: list[list[str]]


@dataclass
class Page:
    """One page of a filing. `page` is 0-indexed (same convention as FinanceBench)."""

    doc_id: str
    page: int
    text: str
    tables: list[Table] = field(default_factory=list)


@dataclass
class ParsedDocument:
    doc_id: str
    pages: list[Page]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    doc_id: str
    page: int
    text: str
    chunk_type: str = "text"  # text | table
    section: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Deterministic id: re-ingesting the same content is a no-op (dedup)."""
        raw = f"{self.doc_id}|{self.page}|{self.chunk_type}|{self.text}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def header(self) -> str:
        parts = [
            self.meta.get("company") or "",
            f"{self.meta.get('form', '')} FY{self.meta.get('year', '')}".strip(),
            self.section,
        ]
        return " | ".join(p for p in parts if p and p != "FY")

    def embed_text(self, contextual_headers: bool) -> str:
        """What gets embedded / keyword-indexed. A table with an LLM summary is retrieved through the summary
        (prose matches questions far better than a grid of numbers); the raw table is still what the LLM reads."""
        body = self.meta.get("summary") or self.text if self.chunk_type == "table" else self.text
        if contextual_headers and self.header():
            return f"{self.header()}\n{body}"
        return body


@dataclass
class Hit:
    chunk: Chunk
    score: float
    source: str = ""  # dense | bm25 | rrf | rerank


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


class DocumentParser(Protocol):
    def parse(self, path: str, doc_id: str) -> ParsedDocument: ...


class Chunker(Protocol):
    def chunk(self, doc: ParsedDocument) -> list[Chunk]: ...


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> np.ndarray: ...


class VectorStore(Protocol):
    def upsert(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None: ...

    def search(
        self, vector: np.ndarray, k: int, filters: dict[str, Any] | None = None
    ) -> list[Hit]: ...

    def save(self, path: str) -> None: ...


class KeywordIndex(Protocol):
    def build(self, chunks: Sequence[Chunk]) -> None: ...

    def search(self, query: str, k: int, filters: dict[str, Any] | None = None) -> list[Hit]: ...


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]: ...


class LLMProvider(Protocol):
    usage: dict[str, int]  # cumulative prompt_tokens / completion_tokens

    def generate(self, messages: list[Message], **kw: Any) -> str: ...

    def stream(self, messages: list[Message], **kw: Any) -> Iterator[str]: ...


class Cache(Protocol):
    def get(self, key: str, vector: np.ndarray | None = None) -> Any | None: ...

    def set(self, key: str, value: Any, vector: np.ndarray | None = None) -> None: ...
