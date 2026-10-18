"""WRITE logic for chat: persist the question, call serving, persist the answer."""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from apps.core.exceptions import DomainError

from .clients import ServingClient
from .models import Conversation, Feedback, Message

# $ per 1M tokens (input, output) keyed by model; local models cost 0. Mirrors ml/evaluation/runner.py.
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.0)}


def merged_filters(conv: Conversation, override: dict[str, Any] | None) -> dict[str, Any]:
    return {**(conv.filters or {}), **{k: v for k, v in (override or {}).items() if v}}


def _save_user_message(conv: Conversation, question: str) -> Message:
    if not conv.title:
        conv.title = question[:80]
        conv.save(update_fields=["title", "updated_at"])
    return Message.objects.create(conversation=conv, role=Message.Role.USER, content=question)


def _cost(usage: dict[str, int], model: str = "") -> Decimal:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return Decimal(str((usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout) / 1e6))


def ask(conv: Conversation, question: str, filters: dict[str, Any] | None = None,
        client: ServingClient | None = None) -> Message:
    client = client or ServingClient()
    _save_user_message(conv, question)
    r = client.query(question, merged_filters(conv, filters))
    return Message.objects.create(
        conversation=conv, role=Message.Role.ASSISTANT, content=r["answer"], citations=r["citations"],
        chunks=r.get("chunks", []), latency_s=r.get("latency_s"), usage=r.get("usage", {}),
        cost_usd=_cost(r.get("usage", {})), cached=r.get("cached", False), refused=r["refused"],
        guardrails={"ok": r["guardrails_ok"]} if r.get("guardrails_ok") is not None else None,
        prompt_version=r.get("prompt_version", ""))


def ask_stream(conv: Conversation, question: str, filters: dict[str, Any] | None = None,
               client: ServingClient | None = None) -> Iterator[str]:
    """Proxy serving's SSE to the browser. Saves the assistant message once the `final` event arrives
    and appends a `saved` event carrying the message id (needed for feedback)."""
    client = client or ServingClient()
    _save_user_message(conv, question)
    chunks: list[Any] = []
    try:
        for ev in client.stream(question, merged_filters(conv, filters)):
            if ev["event"] == "retrieval":
                chunks = ev["data"]["chunks"]
            if ev["event"] == "final":
                d = ev["data"]
                msg = Message.objects.create(
                    conversation=conv, role=Message.Role.ASSISTANT, content=d["answer"], citations=d["citations"],
                    chunks=chunks, latency_s=d.get("latency_s"), refused=d["refused"], guardrails=d.get("guardrails"),
                    prompt_version=d.get("prompt_version", ""))
                yield _frame(ev["event"], d)
                yield _frame("saved", {"message_id": str(msg.id)})
                return
            yield _frame(ev["event"], ev["data"])
    except DomainError as e:
        yield _frame("error", {"code": e.code, "message": e.message})  # type: ignore[attr-defined]


def _frame(event: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data)
    body = "\n".join(f"data: {line}" for line in payload.split("\n"))
    return f"event: {event}\n{body}\n\n"


def give_feedback(message: Message, thumbs_up: bool, comment: str = "") -> Feedback:
    if message.role != Message.Role.ASSISTANT:
        raise DomainError("Feedback can only be given on assistant answers.")
    fb, _ = Feedback.objects.update_or_create(message=message, defaults={"thumbs_up": thumbs_up, "comment": comment})
    return fb
