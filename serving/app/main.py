from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.deps import build_pipeline
from finsight.graph import RAGPipeline


def create_app(pipeline_factory: Callable[[], RAGPipeline] = build_pipeline) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.factory = pipeline_factory
        app.state.pipeline = pipeline_factory()
        yield

    app = FastAPI(title="FinSight serving", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    return app


def get_app() -> FastAPI:
    """uvicorn app.main:get_app --factory  (keeps import side-effect free: no index load at import)."""
    return create_app()
