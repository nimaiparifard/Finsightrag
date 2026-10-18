# ADR 0002: Plain-Python core; LlamaIndex and LangGraph as adapters

**Status:** accepted

## Context

The brief asks for a production RAG that goes beyond a framework tutorial, plus LlamaIndex and LangGraph variants.

## Decision

The **core pipeline is plain Python** behind the interfaces in `interfaces.py`. It is the implementation used by the
product. Two adapters sit on the same index and the same prompt/guardrail code:

* `integrations/llamaindex_impl.py`
  * `finsight` mode: LlamaIndex orchestrates (retriever → response synthesizer) over *our* hybrid + rerank retrieval.
  * `native` mode: a stock `VectorStoreIndex` over the same chunks and vectors (dense only, framework defaults). This
    is the honest "LlamaIndex out of the box" baseline for the ablation.
* `integrations/langgraph_agent.py`: an agent graph (`plan → research → synthesize`) for multi-company comparisons.
  It reuses the core pipeline for each sub-question, so citations and guardrails still apply.

## Why

* Each stage (parse, chunk, retrieve, fuse, rerank, verify) is individually measurable. The ablation table needs that
  control, and a framework's defaults hide it.
* The pipeline stays easy to explain and to debug (the per-answer "debug" drawer shows exactly what was retrieved).
* Using the same index and guardrails across implementations means differences in the results come from
  retrieval/orchestration, not from a different prompt or different data.

## Consequences

LlamaIndex and LangGraph are optional dependencies. `native` mode needs the in-memory (numpy) store.
