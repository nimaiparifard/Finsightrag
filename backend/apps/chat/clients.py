"""HTTP client to the serving microservice: timeouts, bounded retries, typed errors."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
from django.conf import settings

from apps.core.exceptions import UpstreamError


class ServingClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None, retries: int = 2,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base = (base_url or settings.SERVING_URL).rstrip("/")
        self.timeout = httpx.Timeout(timeout or settings.SERVING_TIMEOUT_S, connect=5.0)
        self.retries = retries
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base, timeout=self.timeout, transport=self.transport)

    def query(self, question: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {"question": question, "stream": False, **(filters or {})}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with self._client() as c:
                    r = c.post("/v1/query", json=body)
                if r.status_code >= 500:  # retry only server-side failures, never 4xx
                    raise httpx.HTTPStatusError("server error", request=r.request, response=r)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    raise UpstreamError(f"serving rejected the request: {e.response.text[:300]}") from e
                last = e
            except httpx.TransportError as e:
                last = e
            time.sleep(0.2 * (2 ** attempt))
        raise UpstreamError(f"serving unavailable: {last}")

    def compare(self, question: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Agentic comparison (LangGraph). Slow (one lookup per sub-question), so no retries."""
        try:
            with self._client() as c:
                r = c.post("/v1/compare", json={"question": question, **(filters or {})})
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise UpstreamError(f"serving error {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.TransportError as e:
            raise UpstreamError(f"serving unavailable: {e}") from e

    def stream(self, question: str, filters: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Yields {"event": str, "data": str|dict} parsed from the serving SSE stream."""
        body = {"question": question, "stream": True, **(filters or {})}
        try:
            with self._client() as c, c.stream("POST", "/v1/query", json=body) as r:
                if r.status_code >= 400:
                    r.read()
                    raise UpstreamError(f"serving error {r.status_code}: {r.text[:300]}")
                event, data = "message", []
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].removeprefix(" "))
                    elif line == "":
                        if data:
                            raw = "\n".join(data)
                            yield {"event": event, "data": raw if event == "token" else json.loads(raw)}
                        event, data = "message", []
        except httpx.TransportError as e:
            raise UpstreamError(f"serving unavailable: {e}") from e
