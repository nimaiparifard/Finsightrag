"""Typed configuration. Every knob lives in YAML (see ml/configs/)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ParserCfg(BaseModel):
    name: Literal["pdf", "html"] = "pdf"
    extract_tables: bool = True


class ChunkerCfg(BaseModel):
    name: Literal["recursive", "section"] = "recursive"
    max_tokens: int = 800
    overlap_tokens: int = 100


class EmbedderCfg(BaseModel):
    name: str = "sentence_transformers"
    params: dict[str, Any] = Field(default_factory=lambda: {"model": "BAAI/bge-base-en-v1.5"})


class RerankerCfg(BaseModel):
    name: str = "cross_encoder"
    params: dict[str, Any] = Field(default_factory=lambda: {"model": "BAAI/bge-reranker-v2-m3"})


class RetrievalCfg(BaseModel):
    mode: Literal["dense", "hybrid"] = "dense"
    dense_k: int = 50
    bm25_k: int = 50
    rrf_k: int = 60
    bm25_weight: float = 1.0  # RRF weight of the keyword ranking relative to dense (1.0 = equal)
    rerank: bool = False
    top_k: int = 8
    min_score: float | None = None  # below this on the best hit -> "not found"
    query_transform: Literal["none", "multi_query", "hyde", "decompose"] = "none"
    use_router: bool = False


class LLMCfg(BaseModel):
    provider: str = "openai"
    params: dict[str, Any] = Field(default_factory=lambda: {"model": "gpt-4o-mini"})
    temperature: float = 0.0
    max_tokens: int = 700


class GenerationCfg(BaseModel):
    prompt: str = "answer_v2"
    calculator: bool = True
    guardrails: bool = True
    context_token_budget: int = 6000


class StoreCfg(BaseModel):
    backend: Literal["numpy", "pgvector"] = "numpy"
    dsn_env: str = "FINSIGHT_PG_DSN"  # name of the env var holding the Postgres DSN (keeps secrets out of YAML)


class TableSummaryCfg(BaseModel):
    enabled: bool = False
    min_rows: int = 3  # skip tiny layout tables
    max_per_doc: int = 400  # bound LLM cost per filing


class Config(BaseModel):
    name: str = "baseline"
    parser: ParserCfg = ParserCfg()
    chunker: ChunkerCfg = ChunkerCfg()
    contextual_headers: bool = False
    table_chunks: bool = True
    table_summaries: TableSummaryCfg = TableSummaryCfg()
    store: StoreCfg = StoreCfg()
    embedder: EmbedderCfg = EmbedderCfg()
    reranker: RerankerCfg = RerankerCfg()
    retrieval: RetrievalCfg = RetrievalCfg()
    llm: LLMCfg = LLMCfg()
    generation: GenerationCfg = GenerationCfg()
    index_dir: str = "data/processed/index"
    parsed_dir: str = "data/interim/parsed"

    @model_validator(mode="after")
    def _relocate_data_dir(self) -> Config:
        """FINSIGHT_DATA_DIR moves every 'data/...' path (containers mount the volume elsewhere)."""
        root = os.environ.get("FINSIGHT_DATA_DIR")
        if root:
            for f in ("index_dir", "parsed_dir"):
                v = getattr(self, f)
                if v.startswith("data/"):
                    setattr(self, f, str(Path(root) / v[len("data/"):]))
        return self

    @classmethod
    def load(cls, path: str | Path) -> Config:
        return cls.model_validate(_load_yaml(Path(path)))

    def index_key(self) -> str:
        """Configs that share ingestion settings share one on-disk index."""
        import hashlib
        import json

        spec = {
            "tables_extracted": self.parser.extract_tables,  # parser itself follows the file type
            "chunker": self.chunker.model_dump(),
            "headers": self.contextual_headers,
            "tables": self.table_chunks,
            "embedder": self.embedder.model_dump(),
        }
        if self.table_summaries.enabled:  # only when on, so existing indexes keep their key
            spec["table_summaries"] = self.table_summaries.model_dump()
        return hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    base = raw.pop("extends", None)
    return _deep_merge(_load_yaml(path.parent / base), raw) if base else raw


def _deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
