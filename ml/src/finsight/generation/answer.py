from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from typing import Any, cast

from jinja2 import Template

from finsight.generation.calculator import run_calc_tags_detailed
from finsight.generation.guardrails import NOT_FOUND, GuardrailReport, check_answer, parse_citations
from finsight.interfaces import Hit, LLMProvider, Message
from finsight.text_utils import count_tokens


def load_prompt(name: str) -> Template:
    text = resources.files("finsight.generation").joinpath("prompts", f"{name}.jinja").read_text(encoding="utf-8")
    return cast(Template, Template(text, trim_blocks=False))


def build_context(hits: list[Hit], token_budget: int) -> list[dict[str, Any]]:
    """Keep best-ranked chunks until the token budget is spent. Tables are passed in full."""
    ctx: list[dict[str, Any]] = []
    used = 0
    for h in hits:
        t = count_tokens(h.chunk.text)
        if ctx and used + t > token_budget:
            continue
        ctx.append({"doc_id": h.chunk.doc_id, "page": h.chunk.page, "header": h.chunk.header(),
                    "chunk_type": h.chunk.chunk_type, "text": h.chunk.text})
        used += t
    return ctx


@dataclass
class Answer:
    text: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    guardrails: GuardrailReport | None = None
    calc_values: list[float] = field(default_factory=list)
    prompt_version: str = ""
    refused: bool = False


def build_messages(question: str, hits: list[Hit], *, prompt: str = "answer_v2", calculator: bool = True,
                   token_budget: int = 6000) -> list[Message]:
    ctx = build_context(hits, token_budget)
    example = f"{ctx[0]['doc_id']}:{ctx[0]['page']}" if ctx else "Company_2023_10K:12"
    system = load_prompt(prompt).render(contexts=ctx, calculator=calculator, example_tag=example)
    return [Message("system", system), Message("user", question)]


def finalize_answer(raw: str, hits: list[Hit], *, prompt: str = "answer_v1", calculator: bool = True,
                    guardrails: bool = True) -> Answer:
    """Run <calc> tags, guardrails and citation extraction on the raw model output."""
    text, calc_values, calc_exprs = run_calc_tags_detailed(raw) if calculator else (raw, [], [])
    report = check_answer(text, hits, calc_values, calc_exprs) if guardrails else None
    cites = [{"doc_id": d, "page": p} for d, p in dict.fromkeys(parse_citations(text))]
    return Answer(text=text.strip(), citations=cites, guardrails=report, calc_values=calc_values,
                  prompt_version=prompt, refused=text.strip().startswith(NOT_FOUND[:20]))


def generate_answer(llm: LLMProvider, question: str, hits: list[Hit], *, prompt: str = "answer_v1",
                    calculator: bool = True, guardrails: bool = True, token_budget: int = 6000,
                    temperature: float = 0.0, max_tokens: int = 700) -> Answer:
    msgs = build_messages(question, hits, prompt=prompt, calculator=calculator, token_budget=token_budget)
    raw = llm.generate(msgs, temperature=temperature, max_tokens=max_tokens)
    return finalize_answer(raw, hits, prompt=prompt, calculator=calculator, guardrails=guardrails)
