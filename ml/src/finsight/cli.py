from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, cast

import typer

from finsight.config import Config
from finsight.interfaces import Embedder

app = typer.Typer(no_args_is_help=True, help="FinSight RAG command line")

CONFIG_OPT = typer.Option("ml/configs/baseline.yaml", "--config", "-c", help="YAML config")


def _embedder(cfg: Config) -> Embedder:
    from finsight import registry

    return cast(Embedder, registry.create("embedder", cfg.embedder.name, **cfg.embedder.params))


@app.command()
def ingest(
    config: str = CONFIG_OPT,
    source: str = typer.Option("financebench", help="financebench | pdf-dir | html-dir"),
    path: Optional[str] = typer.Option(None, help="folder for pdf-dir / html-dir"),
    only_eval_docs: bool = typer.Option(True, help="financebench: index only docs the 150 questions use"),
    limit: Optional[int] = typer.Option(None, help="max documents (quick tests)"),
) -> None:
    """Parse, chunk, embed and index documents."""
    from finsight.config import Config
    from finsight.evaluation.datasets import financebench_pdfs, load_financebench
    from finsight.ingestion.pipeline import ingest as run_ingest
    from finsight.store_factory import index_path

    cfg = Config.load(config)
    if source == "financebench":
        wanted = {d for it in load_financebench() for d, _ in it.evidence} if only_eval_docs else None
        docs = financebench_pdfs(doc_ids=wanted)
    elif source in {"pdf-dir", "html-dir"} and path:
        ext = "*.pdf" if source == "pdf-dir" else "*.htm*"
        docs = {p.stem: str(p) for p in sorted(Path(path).rglob(ext))}
    else:
        raise typer.BadParameter("pdf-dir/html-dir need --path")
    if limit:
        docs = dict(list(docs.items())[:limit])
    typer.echo(f"{len(docs)} documents -> {index_path(cfg)}")
    llm = None
    if cfg.table_summaries.enabled:
        from finsight import registry

        llm = registry.create("llm", cfg.llm.provider, **cfg.llm.params)
    store = run_ingest(cfg, docs, _embedder(cfg), llm=llm,
                       progress=lambda n, t, d: typer.echo(f"[{n}/{t}] {d}"))
    typer.echo(f"index: {store.count()} chunks from {len(store.doc_ids())} documents")


@app.command()
def ask(question: str, config: str = CONFIG_OPT, company: Optional[str] = None) -> None:
    """Ask one question against the index."""
    from finsight.config import Config
    from finsight.graph import RAGPipeline

    pipe = RAGPipeline.from_config(Config.load(config))
    res = pipe.query(question, {"company": company} if company else None)
    typer.echo(res.answer.text)
    typer.echo("\nSources: " + ", ".join(f"[{c['doc_id']}:{c['page']}]" for c in res.answer.citations))
    typer.echo(f"({res.latency_s:.1f}s, tokens={res.usage})")


@app.command("eval")
def evaluate(
    config: str = CONFIG_OPT,
    dataset: str = typer.Option("financebench", help="financebench | golden"),
    generate: bool = typer.Option(False, help="also generate answers (needs an LLM)"),
    judge: bool = typer.Option(False, help="LLM-judge faithfulness + answer relevancy (implies --generate)"),
    verified_only: bool = typer.Option(True, help="golden set: only human-verified items"),
    filter_mode: str = typer.Option("router", help="none | router | doc"),
    limit: Optional[int] = None,
    mlflow: bool = typer.Option(False, help="log the run to MLflow"),
) -> None:
    """Evaluate a config. Retrieval metrics need no LLM; --generate adds answer metrics."""
    from finsight.config import Config
    from finsight.evaluation.datasets import load_financebench, load_golden
    from finsight.evaluation.runner import log_mlflow, run_eval, save_run
    from finsight.graph import RAGPipeline

    cfg = Config.load(config)
    items = load_financebench() if dataset == "financebench" else load_golden(only_verified=verified_only)
    items = items[:limit] if limit else items
    pipe = RAGPipeline.from_config(cfg)
    result = run_eval(pipe, items, generate=generate or judge, judge=pipe.llm if judge else None,
                      filter_mode=filter_mode)
    result["dataset"] = dataset
    typer.echo(json.dumps(result["metrics"], indent=2))
    typer.echo(f"saved {save_run(result)}")
    if mlflow:
        log_mlflow(result, cfg.model_dump())


golden = typer.Typer(help="Golden set tooling")
app.add_typer(golden, name="golden")


@golden.command("generate")
def golden_generate(config: str = CONFIG_OPT, out: str = "ml/eval/golden_set.jsonl", seed: int = 7) -> None:
    """Draft ~100 questions with the configured LLM. Every item starts verified=false: review them by hand."""
    from finsight.config import Config
    from finsight.evaluation import golden as g
    from finsight.graph import RAGPipeline

    pipe = RAGPipeline.from_config(Config.load(config))
    items = g.generate(pipe.llm, pipe.store.chunks, seed=seed)
    g.write_jsonl(items, out)
    typer.echo(f"wrote {out}: {g.summary(out)}")
    typer.echo('Next: open the file, fix/delete bad items, set "verified": true on the ones you checked.')


@golden.command("summary")
def golden_summary(path: str = "ml/eval/golden_set.jsonl") -> None:
    from finsight.evaluation import golden as g

    typer.echo(json.dumps(g.summary(path), indent=2))


@app.command()
def gate(
    config: str = CONFIG_OPT,
    baseline: str = typer.Option("ml/eval/baseline_metrics.json", help="saved run JSON to compare against"),
    dataset: str = "golden",
    subset: int = typer.Option(30, help="evaluate only the first N questions (fast PR check)"),
    max_drop: float = typer.Option(0.03, help="allowed absolute drop per metric (0.03 = 3 points)"),
    generate: bool = False,
    judge: bool = False,
) -> None:
    """CI gate: exit 1 if a protected metric regressed by more than --max-drop vs the baseline."""
    from finsight.config import Config
    from finsight.evaluation.datasets import load_financebench, load_golden
    from finsight.evaluation.gate import compare_to_baseline, load_baseline
    from finsight.evaluation.runner import run_eval
    from finsight.graph import RAGPipeline

    cfg = Config.load(config)
    items = (load_financebench() if dataset == "financebench" else load_golden())[:subset]
    if not items:
        typer.echo("no evaluation items (golden set has no verified entries?)", err=True)
        raise typer.Exit(2)
    pipe = RAGPipeline.from_config(cfg)
    res = run_eval(pipe, items, generate=generate or judge, judge=pipe.llm if judge else None, filter_mode="router")
    verdict = compare_to_baseline(res["metrics"], load_baseline(baseline), max_drop)
    typer.echo(verdict.render())
    raise typer.Exit(0 if verdict.passed else 1)


@app.command("eval-tableqa")
def eval_tableqa(
    dataset: str = typer.Option("finqa", help="finqa | tatqa"),
    config: str = CONFIG_OPT,
    n: int = typer.Option(50, help="number of questions"),
    calculator: bool = typer.Option(True, help="--no-calculator to measure the model doing its own arithmetic"),
    out: Optional[str] = None,
) -> None:
    """Numerical reasoning over gold table+text (FinQA / TAT-QA): tests generation + the calculator in isolation."""
    from finsight import registry
    from finsight.config import Config
    from finsight.evaluation.tableqa import load_finqa, load_tatqa, run_tableqa

    cfg = Config.load(config)
    llm = registry.create("llm", cfg.llm.provider, **cfg.llm.params)
    items = (load_finqa() if dataset == "finqa" else load_tatqa())[:n]
    res = run_tableqa(llm, items, calculator=calculator)
    typer.echo(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=2))
    dest = Path(out or f"data/processed/eval/tableqa_{dataset}{'' if calculator else '_nocalc'}.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"config": dest.stem, "dataset": dataset, "n": res["n"], "metrics": {
        k: v for k, v in res.items() if k != "rows"}, "rows": res["rows"]}, indent=2), encoding="utf-8")
    typer.echo(f"saved {dest}")


@app.command()
def report(runs: list[str], out: str = "docs/results.md") -> None:
    """Build the ablation table from saved run files (data/processed/eval/*.json)."""
    from finsight.evaluation.report import markdown_table, write_results

    write_results(runs, out)
    typer.echo(markdown_table(runs))


if __name__ == "__main__":
    app()
