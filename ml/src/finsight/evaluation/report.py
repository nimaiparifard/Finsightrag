"""Turn saved eval runs into the ablation table for README / docs/results.md."""

from __future__ import annotations

import json
from pathlib import Path

COLUMNS = [("recall@5", "Recall@5"), ("hit@5", "Hit@5"), ("mrr", "MRR"), ("ndcg@8", "nDCG@8"),
           ("numeric_em", "Numeric EM"), ("latency_p95_s", "p95 s"), ("cost_per_query", "$/query")]


def markdown_table(run_files: list[str]) -> str:
    head = "| Config | n | " + " | ".join(c[1] for c in COLUMNS) + " |"
    sep = "|---|---|" + "---|" * len(COLUMNS)
    lines = [head, sep]
    for f in run_files:
        r = json.loads(Path(f).read_text(encoding="utf-8"))
        cells = ["-" if r["metrics"].get(k) is None else f"{r['metrics'][k]:.3f}" for k, _ in COLUMNS]
        lines.append(f"| {r['config']} | {r['n']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_results(run_files: list[str], out: str = "docs/results.md") -> None:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Results\n\n" + markdown_table(run_files) + "\n", encoding="utf-8")
