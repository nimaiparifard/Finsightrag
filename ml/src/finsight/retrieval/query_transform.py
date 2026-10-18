from __future__ import annotations

import json
import re
from typing import Any

from finsight.interfaces import LLMProvider, Message


def _ask(llm: LLMProvider, system: str, user: str, max_tokens: int = 300) -> str:
    return llm.generate([Message("system", system), Message("user", user)], temperature=0.0, max_tokens=max_tokens)


def _json_object(text: str) -> Any:
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    return json.loads(m.group(0)) if m else None


def multi_query(llm: LLMProvider, question: str, n: int = 3) -> list[str]:
    out = _ask(llm, f"Rewrite the finance question as {n} differently worded search queries. "
                    "Return a JSON list of strings only.", question)
    try:
        qs = [q for q in _json_object(out) if isinstance(q, str)]
    except Exception:
        qs = []
    return [question] + qs[:n]


def hyde(llm: LLMProvider, question: str) -> list[str]:
    """Hypothetical Document Embeddings: search with a fake passage that would answer the question."""
    passage = _ask(llm, "Write a short passage, in the style of an SEC 10-K filing, that would answer "
                        "the question. Invent plausible wording; do not add disclaimers.", question)
    return [question, passage] if passage.strip() else [question]


def decompose(llm: LLMProvider, question: str) -> list[str]:
    """'Compare A and B on X' -> one sub-question per entity/period."""
    out = _ask(llm, "If the question compares several companies, years or metrics, split it into "
                    "independent single-fact sub-questions. Return a JSON list of strings; "
                    "return [] if it is already a single-fact question.", question)
    try:
        subs = [q for q in _json_object(out) if isinstance(q, str)]
    except Exception:
        subs = []
    return [question] + subs[:6]


def transform(mode: str, llm: LLMProvider | None, question: str) -> list[str]:
    if mode == "none" or llm is None:
        return [question]
    return {"multi_query": multi_query, "hyde": hyde, "decompose": decompose}[mode](llm, question)
