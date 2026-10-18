"""name -> factory maps. Swapping a component is a one-line YAML change."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_REGISTRIES: dict[str, dict[str, Callable[..., Any]]] = {
    "embedder": {},
    "reranker": {},
    "llm": {},
}


def register(kind: str, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(factory: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRIES[kind][name] = factory
        return factory

    return deco


def create(kind: str, name: str, **params: Any) -> Any:
    _load_builtin_plugins()
    try:
        return _REGISTRIES[kind][name](**params)
    except KeyError:
        known = ", ".join(sorted(_REGISTRIES[kind]))
        raise ValueError(f"unknown {kind} '{name}' (known: {known})") from None


def _load_builtin_plugins() -> None:
    # imported lazily so heavy deps (torch, openai) load only when used
    from finsight import embedders, llm  # noqa: F401
    from finsight.retrieval import rerankers  # noqa: F401
