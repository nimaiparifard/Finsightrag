"""Optional Langfuse tracing. If the SDK or keys are missing every call is a cheap no-op,
so the pipeline never depends on the tracing backend being up."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class _NullSpan:
    def update(self, **_: Any) -> None: ...


class Tracer:
    def __init__(self) -> None:
        self.client: Any = None
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse import Langfuse

                self.client = Langfuse()
            except Exception:
                self.client = None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def trace(self, name: str, **meta: Any) -> Iterator[Any]:
        if not self.client:
            yield _NullSpan()
            return
        try:
            with self.client.start_as_current_span(name=name, input=meta) as span:
                yield span
        except Exception:
            yield _NullSpan()

    def flush(self) -> None:
        if self.client:
            try:
                self.client.flush()
            except Exception:
                pass


tracer = Tracer()
