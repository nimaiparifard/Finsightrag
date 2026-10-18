from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    company: list[str] | None = None
    year: list[str] | None = None
    form: str | None = None
    stream: bool = True

    def filters(self) -> dict[str, Any] | None:
        f: dict[str, Any] = {}
        if self.company:
            f["company"] = self.company
        if self.year:
            f["year"] = self.year
        if self.form:
            f["form"] = self.form
        return f or None


class Citation(BaseModel):
    doc_id: str
    page: int


class ChunkOut(BaseModel):
    doc_id: str
    page: int
    score: float
    type: str
    section: str = ""
    preview: str = ""


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool
    cached: bool = False
    latency_s: float
    guardrails_ok: bool | None = None
    prompt_version: str = ""
    chunks: list[ChunkOut] = []
    usage: dict[str, int] = {}


class RetrieveResponse(BaseModel):
    filters: dict[str, Any]
    type: str
    timings: dict[str, float]
    chunks: list[ChunkOut]
