from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from finsight.evaluation.datasets import EvalItem
from finsight.evaluation.judge import judge_answer
from finsight.evaluation.numeric import numeric_match
from finsight.evaluation.retrieval_metrics import hit_at_k, mrr, ndcg_at_k, recall_at_k
from finsight.graph import RAGPipeline

# $ per 1M tokens (input, output). Extend as needed; unknown models report cost 0.
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.0)}


def _filters(mode: str, item: EvalItem) -> dict[str, Any] | None:
    """none: open retrieval over the whole corpus; doc: restrict to the gold document;
    router: let the pipeline infer company filters from the question text."""
    if mode == "doc" and item.evidence:
        return {"doc_id": sorted({d for d, _ in item.evidence})}
    if mode == "none":
        return {}
    return None


def run_eval(pipe: RAGPipeline, items: list[EvalItem], *, generate: bool = False, judge: Any = None,
             filter_mode: str = "router", ks: tuple[int, ...] = (1, 5, 8)) -> dict[str, Any]:
    """judge: an LLMProvider used for faithfulness / answer relevancy (needs generate=True)."""
    rows, lat = [], []
    for it in items:
        t0 = time.perf_counter()
        f = _filters(filter_mode, it)
        row: dict[str, Any] = {"id": it.id, "type": it.qtype}
        if generate:
            try:
                res = pipe.query(it.question, f)
            except Exception as e:  # one slow/failed LLM call must not lose a long run: record it and move on
                rows.append({**row, "error": f"{type(e).__name__}: {e}"[:300]})
                lat.append(time.perf_counter() - t0)
                continue
            ret = res.retrieval
            row.update(answer=res.answer.text, refused=res.answer.refused, cost=_cost(pipe, res.usage),
                       numeric=numeric_match(res.answer.text, it.answer) if it.answerable else None,
                       guardrails_ok=res.answer.guardrails.ok if res.answer.guardrails else None)
            if judge is not None and it.answerable:
                j = judge_answer(judge, it.question, res.answer.text, res.retrieval.hits)
                row.update(faithfulness=j.faithfulness, answer_relevancy=j.answer_relevancy)
        else:
            ret = pipe.retrieve(it.question, f)
        lat.append(time.perf_counter() - t0)
        if it.answerable and it.gold:
            row.update({f"recall@{k}": recall_at_k(ret.hits, it.gold, k) for k in ks})
            row.update({f"hit@{k}": hit_at_k(ret.hits, it.gold, k) for k in ks})
            row["mrr"] = mrr(ret.hits, it.gold)
            row["ndcg@8"] = ndcg_at_k(ret.hits, it.gold, 8)
        rows.append(row)

    def avg(key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(statistics.mean(vals), 4) if vals else None

    metrics: dict[str, Any] = {k: avg(k) for k in
                               [f"recall@{k}" for k in ks] + [f"hit@{k}" for k in ks] + ["mrr", "ndcg@8"]}
    srt = sorted(lat)
    metrics["errors"] = sum(1 for r in rows if "error" in r)
    metrics["latency_p50_s"] = round(srt[len(srt) // 2], 3)
    metrics["latency_p95_s"] = round(srt[min(len(srt) - 1, int(len(srt) * 0.95))], 3)
    if generate:
        metrics["numeric_em"] = avg("numeric")
        if judge is not None:
            metrics["faithfulness"] = avg("faithfulness")
            metrics["answer_relevancy"] = avg("answer_relevancy")
        metrics["cost_per_query"] = round(sum(r.get("cost", 0.0) for r in rows) / max(1, sum("error" not in r for r in rows)), 5)
        un = [r for r, it in zip(rows, items) if not it.answerable and "error" not in r]
        if un:
            metrics["refusal_accuracy"] = round(sum(r["refused"] for r in un) / len(un), 4)
        g = [r["guardrails_ok"] for r in rows if r.get("guardrails_ok") is not None]
        if g:
            metrics["guardrails_pass_rate"] = round(sum(g) / len(g), 4)
    return {"config": pipe.cfg.name, "n": len(items), "metrics": metrics, "rows": rows}


def _cost(pipe: RAGPipeline, usage: dict[str, int]) -> float:
    model = str(pipe.cfg.llm.params.get("model", ""))
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout) / 1e6


def save_run(result: dict[str, Any], out_dir: str = "data/processed/eval") -> Path:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    path = p / f"{result['config']}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path


def log_mlflow(result: dict[str, Any], cfg_dump: dict[str, Any]) -> None:
    try:
        import mlflow
    except ImportError:
        return
    mlflow.set_experiment("finsight-rag")
    with mlflow.start_run(run_name=result["config"]):
        mlflow.log_params({k: str(v)[:250] for k, v in _flatten(cfg_dump).items()})
        mlflow.log_metrics({k: v for k, v in result["metrics"].items() if v is not None})


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        out.update(_flatten(v, key + ".") if isinstance(v, dict) else {key: v})
    return out
