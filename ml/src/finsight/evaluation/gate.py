"""CI quality gate: fail when a gated metric drops more than `max_drop` (absolute) below the stored baseline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

# higher is better for all of these; latency/cost are reported but not gated here
GATED = ("recall@5", "mrr", "faithfulness", "answer_relevancy", "numeric_em", "refusal_accuracy")


@dataclass
class GateResult:
    passed: bool
    rows: list[dict[str, Any]]

    def render(self) -> str:
        lines = ["| metric | baseline | current | delta | status |", "|---|---|---|---|---|"]
        for r in self.rows:
            lines.append(f"| {r['metric']} | {r['baseline']:.3f} | {r['current']:.3f} | {r['delta']:+.3f} | {r['status']} |")
        return "\n".join(lines)


def compare_to_baseline(current: dict[str, Any], baseline: dict[str, Any], max_drop: float = 0.03) -> GateResult:
    rows, ok = [], True
    for m in GATED:
        b, c = baseline.get(m), current.get(m)
        if b is None:
            continue  # not part of the baseline: nothing to protect
        if c is None:
            rows.append({"metric": m, "baseline": b, "current": float("nan"), "delta": float("nan"), "status": "MISSING"})
            ok = False  # a metric silently disappearing must not pass the gate
            continue
        delta = c - b
        bad = delta < -max_drop - 1e-9
        ok &= not bad
        rows.append({"metric": m, "baseline": b, "current": c, "delta": delta, "status": "FAIL" if bad else "ok"})
    return GateResult(ok, rows)


def load_baseline(path: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8"))["metrics"])
