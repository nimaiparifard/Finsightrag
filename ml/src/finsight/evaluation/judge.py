"""LLM-as-judge metrics in the spirit of RAGAS (implemented directly so they run with any LLMProvider, including a
local model, and can be unit-tested with a fake one):

  faithfulness      = supported claims / claims, where the judge extracts the answer's claims and checks each one
                      against the retrieved context only
  answer_relevancy  = judge rates 1-5 whether the answer addresses the question, mapped to 0..1

Judges are noisy: use a stronger model than the one being evaluated where you can, and report n.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from finsight.generation.guardrails import NOT_FOUND
from finsight.interfaces import Hit, LLMProvider, Message

FAITH_SYSTEM = (
    "You are a strict fact-checker. You get a CONTEXT (excerpts from SEC filings) and an ANSWER. "
    "1) Split the ANSWER into atomic factual claims (ignore citations like [doc:page]). "
    "2) For each claim decide if the CONTEXT alone supports it (numbers must match; arithmetic that follows "
    "directly from context numbers counts as supported). "
    'Reply with JSON only: {"claims": [{"claim": "...", "supported": true|false}]}'
)
REL_SYSTEM = (
    "Rate how well the ANSWER addresses the QUESTION on a 1-5 scale (5 = fully and directly answers, "
    '1 = unrelated or evasive). Ignore correctness. Reply with JSON only: {"score": <1-5>}'
)


@dataclass
class JudgeResult:
    faithfulness: float | None
    answer_relevancy: float | None
    claims: int = 0


def _json(text: str) -> Any:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def judge_answer(judge: LLMProvider, question: str, answer: str, hits: list[Hit],
                 max_context_chars: int = 12000) -> JudgeResult:
    if answer.strip().startswith(NOT_FOUND[:20]):  # a refusal makes no claims; relevance is not meaningful either
        return JudgeResult(None, None)
    ctx = "\n\n".join(f"[{h.chunk.doc_id}:{h.chunk.page}] {h.chunk.text}" for h in hits)[:max_context_chars]
    faith: float | None = None
    claims = 0
    data = _json(judge.generate([Message("system", FAITH_SYSTEM),
                                 Message("user", f"CONTEXT:\n{ctx}\n\nANSWER:\n{answer}")],
                                temperature=0.0, max_tokens=800))
    if data and isinstance(data.get("claims"), list) and data["claims"]:
        verdicts = [bool(c.get("supported")) for c in data["claims"] if isinstance(c, dict)]
        claims = len(verdicts)
        faith = sum(verdicts) / claims if claims else None
    rel: float | None = None
    r = _json(judge.generate([Message("system", REL_SYSTEM), Message("user", f"QUESTION: {question}\n\nANSWER: {answer}")],
                             temperature=0.0, max_tokens=30))
    try:
        score = float(r["score"]) if r else None
        rel = (min(5.0, max(1.0, score)) - 1) / 4 if score is not None else None
    except (KeyError, TypeError, ValueError):
        rel = None
    return JudgeResult(faith, rel, claims)
