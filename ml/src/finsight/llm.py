from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any, cast

from finsight.interfaces import Message
from finsight.registry import register


class _UsageMixin:
    def _init_usage(self) -> None:
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}


@register("llm", "openai")
class OpenAIProvider(_UsageMixin):
    """OpenAI, and anything speaking its protocol: vLLM, Ollama (base_url=http://localhost:11434/v1)."""

    def __init__(self, model: str = "gpt-4o-mini", base_url: str | None = None,
                 api_key_env: str = "OPENAI_API_KEY", **_: Any) -> None:
        from openai import OpenAI

        self._init_usage()
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=os.environ.get(api_key_env, "not-needed"))

    def generate(self, messages: list[Message], **kw: Any) -> str:
        r = self.client.chat.completions.create(
            model=self.model, messages=cast(Any, [m.__dict__ for m in messages]),
            temperature=kw.get("temperature", 0.0), max_tokens=kw.get("max_tokens", 700),
        )
        if r.usage:
            self.usage["prompt_tokens"] += r.usage.prompt_tokens
            self.usage["completion_tokens"] += r.usage.completion_tokens
        return r.choices[0].message.content or ""

    def stream(self, messages: list[Message], **kw: Any) -> Iterator[str]:
        s = self.client.chat.completions.create(
            model=self.model, messages=cast(Any, [m.__dict__ for m in messages]), stream=True,
            temperature=kw.get("temperature", 0.0), max_tokens=kw.get("max_tokens", 700),
        )
        for ev in s:
            if ev.choices and ev.choices[0].delta.content:
                yield ev.choices[0].delta.content


@register("llm", "anthropic")
class AnthropicProvider(_UsageMixin):
    def __init__(self, model: str = "claude-haiku-5-5", api_key_env: str = "ANTHROPIC_API_KEY", **_: Any) -> None:
        import anthropic

        self._init_usage()
        self.model = model
        self.client = anthropic.Anthropic(api_key=os.environ.get(api_key_env))

    @staticmethod
    def _split(messages: list[Message]) -> tuple[str, list[dict[str, str]]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        return system, [m.__dict__ for m in messages if m.role != "system"]

    def generate(self, messages: list[Message], **kw: Any) -> str:
        system, msgs = self._split(messages)
        r = self.client.messages.create(
            # no temperature: current Anthropic models/SDK do not accept sampling parameters
            model=self.model, system=system, messages=cast(Any, msgs), max_tokens=kw.get("max_tokens", 700),
        )
        self.usage["prompt_tokens"] += r.usage.input_tokens
        self.usage["completion_tokens"] += r.usage.output_tokens
        return "".join(b.text for b in r.content if b.type == "text")

    def stream(self, messages: list[Message], **kw: Any) -> Iterator[str]:
        system, msgs = self._split(messages)
        with self.client.messages.stream(
            # no temperature: current Anthropic models/SDK do not accept sampling parameters
            model=self.model, system=system, messages=cast(Any, msgs), max_tokens=kw.get("max_tokens", 700),
        ) as s:
            yield from s.text_stream


@register("llm", "fake")
class FakeLLMProvider(_UsageMixin):
    """Deterministic provider for tests: `responder(messages) -> str` or a fixed reply."""

    def __init__(self, reply: str = "I don't know.", responder: Callable[[list[Message]], str] | None = None,
                 **_: Any) -> None:
        self._init_usage()
        self.reply, self.responder = reply, responder
        self.calls: list[list[Message]] = []

    def generate(self, messages: list[Message], **kw: Any) -> str:
        self.calls.append(messages)
        return self.responder(messages) if self.responder else self.reply

    def stream(self, messages: list[Message], **kw: Any) -> Iterator[str]:
        yield from self.generate(messages, **kw).split(" ")


def ollama_host(explicit: str | None = None) -> str:
    """explicit arg > $OLLAMA_HOST > localhost. Ollama itself allows 'host:port' without a scheme."""
    h = explicit or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    if "://" not in h:
        h = "http://" + h.replace("0.0.0.0", "localhost")
    return h.rstrip("/")


# ---- Ollama (native API: lets us set num_ctx; the OpenAI-compat endpoint truncates at 2048) ----
@register("llm", "ollama")
class OllamaProvider(_UsageMixin):
    def __init__(self, model: str = "qwen2.5:7b-instruct", host: str | None = None,
                 num_ctx: int = 8192, timeout: float = 300.0, **_: Any) -> None:
        self._init_usage()
        self.model, self.num_ctx, self.timeout = model, num_ctx, timeout
        self.host = ollama_host(host)

    def _body(self, messages: list[Message], stream: bool, kw: dict[str, Any]) -> dict[str, Any]:
        return {"model": self.model, "stream": stream, "messages": [m.__dict__ for m in messages],
                "options": {"temperature": kw.get("temperature", 0.0), "num_ctx": self.num_ctx,
                            "num_predict": kw.get("max_tokens", 700)}}

    def _count(self, d: dict[str, Any]) -> None:
        self.usage["prompt_tokens"] += d.get("prompt_eval_count", 0)
        self.usage["completion_tokens"] += d.get("eval_count", 0)

    def generate(self, messages: list[Message], **kw: Any) -> str:
        import requests

        r = requests.post(f"{self.host}/api/chat", json=self._body(messages, False, kw), timeout=self.timeout)
        r.raise_for_status()
        d = r.json()
        self._count(d)
        return str(d["message"]["content"])

    def stream(self, messages: list[Message], **kw: Any) -> Iterator[str]:
        import json

        import requests

        with requests.post(f"{self.host}/api/chat", json=self._body(messages, True, kw),
                           stream=True, timeout=self.timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if d.get("done"):
                    self._count(d)
                else:
                    yield d["message"]["content"]


# ---- OpenAI-protocol presets: same class, different base_url / key / default model ----
_PRESETS = {
    "vllm": ("http://localhost:8000/v1", "VLLM_API_KEY", "Qwen/Qwen2.5-7B-Instruct"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openai/gpt-4o-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.0-flash"),
}


def _register_preset(name: str, base_url: str, key_env: str, default_model: str) -> None:
    def factory(model: str = default_model, **kw: Any) -> OpenAIProvider:
        kw.setdefault("base_url", base_url)
        kw.setdefault("api_key_env", key_env)
        return OpenAIProvider(model=model, **kw)

    register("llm", name)(factory)


for _name, (_url, _env, _model) in _PRESETS.items():
    _register_preset(_name, _url, _env, _model)


# ---- auto: use whichever backend is actually reachable ----
def detect_provider() -> tuple[str, dict[str, Any]]:
    """Order: hosted APIs with a key in the environment, then a local Ollama that has a model."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", {}
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", {}
    for name, (_, env, _) in _PRESETS.items():
        if os.environ.get(env):
            return name, {}
    try:
        import requests

        models = [m["name"] for m in requests.get(f"{ollama_host()}/api/tags", timeout=2).json().get("models", [])]
        if models:
            preferred = next((m for m in models if m.startswith("qwen2.5")), models[0])
            return "ollama", {"model": preferred}
    except Exception:
        pass
    raise RuntimeError("No LLM available: set ANTHROPIC_API_KEY / OPENAI_API_KEY / GROQ_API_KEY / ..., "
                       "or start Ollama and `ollama pull qwen2.5:7b-instruct`.")


@register("llm", "auto")
def _auto(**kw: Any) -> Any:
    from finsight.registry import create

    name, params = detect_provider()
    return create("llm", name, **{**params, **kw})
