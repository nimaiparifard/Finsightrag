from __future__ import annotations

import os

from fastapi import Request

from finsight.cache import InMemorySemanticCache, RedisSemanticCache
from finsight.config import Config
from finsight.graph import RAGPipeline


def build_pipeline() -> RAGPipeline:
    cfg = Config.load(os.environ.get("FINSIGHT_CONFIG", "ml/configs/dense_rerank_ctx.yaml"))
    redis_url = os.environ.get("REDIS_URL")
    cache = (RedisSemanticCache(redis_url, threshold=0.95, ttl_s=86400) if redis_url
             else InMemorySemanticCache(0.95))
    return RAGPipeline.from_config(cfg, cache=cache)


def get_pipeline(request: Request) -> RAGPipeline:
    return request.app.state.pipeline
