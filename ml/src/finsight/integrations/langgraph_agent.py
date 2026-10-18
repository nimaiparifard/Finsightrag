"""Agentic comparison mode (LangGraph):  plan -> research each sub-question -> synthesize -> verify.

The core pipeline answers one question. For "Compare Apple and Microsoft operating margin in FY2023" the agent
splits it into single-fact sub-questions, runs the full RAG flow on each (with its own company filter), then writes
a comparison using only the sub-answers, so every number is still traceable to a cited page."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from finsight.generation.answer import Answer, finalize_answer
from finsight.generation.guardrails import NOT_FOUND
from finsight.graph import RAGPipeline
from finsight.interfaces import Hit, Message
from finsight.retrieval.query_transform import decompose
from finsight.router import heuristic_route


class AgentState(TypedDict, total=False):
    question: str
    sub_questions: list[str]
    findings: list[dict[str, Any]]
    hits: list[Hit]
    answer: Answer
    trace: list[str]


SYNTH_SYSTEM = (
    "You are FinSight. Write a concise comparison answering the QUESTION using ONLY the FINDINGS below. "
    "Keep the [doc_id:page] citations from the findings on every sentence that states a fact. "
    "Do arithmetic only inside <calc>...</calc> with plain numbers. If a finding says it was not found, "
    f'say that part could not be found rather than guessing. If nothing is usable reply "{NOT_FOUND}"'
)


class ComparisonAgent:
    def __init__(self, pipe: RAGPipeline, max_subquestions: int = 6) -> None:
        self.pipe, self.max_sub = pipe, max_subquestions
        g = StateGraph(AgentState)
        # langgraph's overloads do not accept partial-update TypedDict returns; the runtime contract is fine
        g.add_node("plan", self._plan)  # type: ignore[call-overload]
        g.add_node("research", self._research)  # type: ignore[call-overload]
        g.add_node("synthesize", self._synthesize)  # type: ignore[call-overload]
        g.add_edge(START, "plan")
        g.add_edge("plan", "research")
        g.add_edge("research", "synthesize")
        g.add_edge("synthesize", END)
        self.graph = g.compile()

    # ---- nodes ----------------------------------------------------------------------------
    def _plan(self, s: AgentState) -> AgentState:
        subs = decompose(self.pipe.llm, s["question"])[1: 1 + self.max_sub]
        subs = subs or [s["question"]]
        return {"sub_questions": subs, "trace": [f"plan: {len(subs)} sub-question(s)"]}

    def _research(self, s: AgentState) -> AgentState:
        findings, hits = [], []
        for q in s["sub_questions"]:
            res = self.pipe.query(q)  # full flow: route -> retrieve -> rerank -> generate -> verify
            findings.append({"question": q, "answer": res.answer.text, "refused": res.answer.refused,
                             "filters": res.retrieval.route.filters})
            hits += res.retrieval.hits
        return {"findings": findings, "hits": hits,
                "trace": s.get("trace", []) + [f"research: {len(findings)} lookups"]}

    def _synthesize(self, s: AgentState) -> AgentState:
        found = [f for f in s["findings"] if not f["refused"]]
        if not found:
            return {"answer": Answer(text=NOT_FOUND, refused=True)}
        if len(s["findings"]) == 1:  # nothing to combine: reuse the single verified answer
            raw = s["findings"][0]["answer"]
        else:
            body = "\n".join(f"- Q: {f['question']}\n  A: {f['answer']}" for f in s["findings"])
            raw = self.pipe.llm.generate(
                [Message("system", SYNTH_SYSTEM), Message("user", f"QUESTION: {s['question']}\n\nFINDINGS:\n{body}")],
                temperature=0.0, max_tokens=self.pipe.cfg.llm.max_tokens)
        # verify against every chunk the sub-questions retrieved
        g = self.pipe.cfg.generation
        ans = finalize_answer(raw, _dedup(s["hits"]), prompt=g.prompt, calculator=g.calculator, guardrails=g.guardrails)
        return {"answer": ans, "trace": s.get("trace", []) + ["synthesize"]}

    def run(self, question: str) -> AgentState:
        return cast(AgentState, self.graph.invoke({"question": question}))


def _dedup(hits: list[Hit]) -> list[Hit]:
    return list({h.chunk.id: h for h in hits}.values())


def is_comparison(question: str, companies: set[str]) -> bool:
    r = heuristic_route(question, companies)
    return r.qtype == "comparison" or len(r.filters.get("company", [])) > 1
