"""The real providers, tested against stubbed SDK clients / HTTP: no network, no keys."""

import json
from types import SimpleNamespace as NS

import pytest

from finsight import registry
from finsight.interfaces import Message
from finsight.llm import AnthropicProvider, OllamaProvider, OpenAIProvider, detect_provider

MSGS = [Message("system", "be brief"), Message("user", "hi")]


# ---- OpenAI-compatible ------------------------------------------------------------------------
class FakeOpenAI:
    def __init__(self):
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if kw.get("stream"):
            return iter([NS(choices=[NS(delta=NS(content="Hel"))]), NS(choices=[]), NS(choices=[NS(delta=NS(content="lo"))])])
        return NS(choices=[NS(message=NS(content="Hello"))], usage=NS(prompt_tokens=11, completion_tokens=3))


def test_openai_generate_stream_and_usage():
    p = OpenAIProvider.__new__(OpenAIProvider)
    p._init_usage()
    p.model, p.client = "m", FakeOpenAI()
    assert p.generate(MSGS, max_tokens=50) == "Hello" and p.usage == {"prompt_tokens": 11, "completion_tokens": 3}
    sent = p.client.calls[0]
    assert sent["messages"] == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]
    assert sent["max_tokens"] == 50 and sent["temperature"] == 0.0
    assert "".join(p.stream(MSGS)) == "Hello"  # empty-choices keepalive chunks are skipped


def test_presets_point_at_the_right_endpoints(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    llm = registry.create("llm", "groq")
    assert "groq.com" in str(llm.client.base_url) and llm.model == "llama-3.3-70b-versatile"
    assert registry.create("llm", "vllm", model="x").model == "x"


# ---- Anthropic --------------------------------------------------------------------------------
class FakeAnthropic:
    def __init__(self):
        self.calls = []
        self.messages = NS(create=self._create, stream=self._stream)

    def _create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(type="text", text="Hel"), NS(type="thinking", text="x"), NS(type="text", text="lo")],
                  usage=NS(input_tokens=7, output_tokens=2))

    def _stream(self, **kw):
        self.calls.append(kw)
        ctx = NS(__enter__=lambda s: NS(text_stream=iter(["a", "b"])), __exit__=lambda s, *a: False)

        class CM:
            def __enter__(self):
                return NS(text_stream=iter(["a", "b"]))

            def __exit__(self, *a):
                return False

        del ctx
        return CM()


def test_anthropic_never_sends_unsupported_sampling_params():
    p = AnthropicProvider.__new__(AnthropicProvider)
    p._init_usage()
    p.model, p.client = "m", FakeAnthropic()
    assert p.generate(MSGS, temperature=0.7) == "Hello" and p.usage == {"prompt_tokens": 7, "completion_tokens": 2}
    sent = p.client.calls[0]
    assert sent["system"] == "be brief" and sent["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in sent  # current Anthropic SDK/models reject it
    assert "".join(p.stream(MSGS)) == "ab" and "temperature" not in p.client.calls[1]


# ---- Ollama (native HTTP API) ---------------------------------------------------------------------
def test_ollama_sets_context_window_and_counts_tokens(monkeypatch):
    import requests

    sent = {}

    class Resp:
        def __init__(self, payload=None, lines=None):
            self.payload, self.lines = payload, lines

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

        def iter_lines(self):
            return iter(self.lines)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def post(url, json=None, stream=False, timeout=0):
        sent.update(url=url, body=json)
        if stream:
            return Resp(lines=[b'{"message":{"content":"Hi"},"done":false}', b"",
                               b'{"message":{"content":""},"done":true,"prompt_eval_count":5,"eval_count":2}'])
        return Resp({"message": {"content": "Hello"}, "prompt_eval_count": 40, "eval_count": 9})

    monkeypatch.setattr(requests, "post", post)
    p = OllamaProvider(model="qwen2.5:7b-instruct", num_ctx=8192)
    assert p.generate(MSGS, max_tokens=64) == "Hello" and p.usage == {"prompt_tokens": 40, "completion_tokens": 9}
    assert sent["url"].endswith("/api/chat") and sent["body"]["stream"] is False
    # without num_ctx Ollama silently truncates long prompts at 2048 tokens: it must always be sent
    assert sent["body"]["options"] == {"temperature": 0.0, "num_ctx": 8192, "num_predict": 64}
    assert "".join(p.stream(MSGS)) == "Hi" and p.usage["prompt_tokens"] == 45


# ---- auto-detection ---------------------------------------------------------------------------------
@pytest.fixture
def clean_env(monkeypatch):
    for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY", "OPENROUTER_API_KEY",
              "GEMINI_API_KEY", "VLLM_API_KEY"]:
        monkeypatch.delenv(k, raising=False)


def test_auto_prefers_env_keys_then_ollama(clean_env, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: NS(json=lambda: {"models": [{"name": "llama3"}, {"name": "qwen2.5:7b-instruct"}]}))
    assert detect_provider() == ("ollama", {"model": "qwen2.5:7b-instruct"})  # prefers the qwen2.5 model
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert detect_provider()[0] == "groq"
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert detect_provider()[0] == "openai"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert detect_provider()[0] == "anthropic"


def test_auto_fails_clearly_when_nothing_is_available(clean_env, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: NS(json=lambda: {"models": []}))
    with pytest.raises(RuntimeError, match="No LLM available"):
        detect_provider()
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    with pytest.raises(RuntimeError, match="ollama pull"):
        detect_provider()
    assert json  # (json imported for parity with other provider tests)


def test_ollama_host_resolution(monkeypatch):
    from finsight.llm import ollama_host

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert ollama_host() == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11435")  # Ollama's own convention: no scheme
    assert ollama_host() == "http://localhost:11435"
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:11434/")
    assert ollama_host() == "http://gpu-box:11434" and OllamaProvider().host == "http://gpu-box:11434"
    assert ollama_host("http://other:1") == "http://other:1"  # explicit wins
