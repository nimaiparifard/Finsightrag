"""FinQA / TAT-QA: numerical reasoning over a table + text. They test the *generation + calculator* path in
isolation: the gold context is handed to the model (no retrieval), so a miss is a reasoning/arithmetic miss."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finsight.evaluation.numeric import numeric_match
from finsight.generation.answer import generate_answer
from finsight.ingestion.parsers.pdf_parser import rows_to_markdown
from finsight.interfaces import Chunk, Hit, LLMProvider


@dataclass
class TableQAItem:
    id: str
    question: str
    answer: str
    table_rows: list[list[str]]
    text: str
    source: str  # finqa | tatqa
    answer_type: str = ""  # tatqa: span | multi-span | arithmetic | count


def load_finqa(root: str = "data/raw/finqa", split: str = "test") -> list[TableQAItem]:
    data = json.loads((Path(root) / "dataset" / f"{split}.json").read_text(encoding="utf-8"))
    out = []
    for r in data:
        qa = r["qa"]
        text = " ".join(r.get("pre_text", []) + r.get("post_text", []))
        out.append(TableQAItem(r["id"], qa["question"], str(qa["answer"]), r["table"], text, "finqa",
                               "arithmetic" if qa.get("program") else ""))
    return out


def load_tatqa(root: str = "data/raw/tatqa", split: str = "dev", numeric_only: bool = True) -> list[TableQAItem]:
    data = json.loads((Path(root) / "dataset_raw" / f"tatqa_dataset_{split}.json").read_text(encoding="utf-8"))
    out = []
    for doc in data:
        text = " ".join(p["text"] for p in sorted(doc["paragraphs"], key=lambda p: p["order"]))
        for q in doc["questions"]:
            ans = q["answer"]
            ans = " ".join(map(str, ans)) if isinstance(ans, list) else str(ans)
            if numeric_only and q["answer_type"] not in {"arithmetic", "count"} and not any(c.isdigit() for c in ans):
                continue
            out.append(TableQAItem(q["uid"], q["question"], ans, doc["table"]["table"], text, "tatqa", q["answer_type"]))
    return out


def to_hits(item: TableQAItem) -> list[Hit]:
    meta = {"company": item.source}
    chunks = [Chunk(item.id, 0, rows_to_markdown(item.table_rows), "table", meta=meta)] if item.table_rows else []
    if item.text:
        chunks.append(Chunk(item.id, 0, item.text, "text", meta=meta))
    return [Hit(c, 1.0, "gold") for c in chunks]


def run_tableqa(llm: LLMProvider, items: list[TableQAItem], *, calculator: bool = True,
                max_tokens: int = 400) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for it in items:
        ans = generate_answer(llm, it.question, to_hits(it), calculator=calculator, guardrails=True,
                              max_tokens=max_tokens)
        ok = numeric_match(ans.text, it.answer)
        rows.append({"id": it.id, "type": it.answer_type, "correct": bool(ok), "scored": ok is not None,
                     "used_calc": bool(ans.calc_values), "guardrails_ok": ans.guardrails.ok if ans.guardrails else None,
                     "answer": ans.text})
    scored = [r for r in rows if r["scored"]]
    calc_rows = [r for r in scored if r["used_calc"]]
    return {"n": len(rows), "numeric_em": round(statistics.mean(float(r["correct"]) for r in scored), 4) if scored else None,
            "used_calculator_rate": round(len(calc_rows) / len(scored), 4) if scored else None,
            "em_when_calculator_used": round(statistics.mean(float(r["correct"]) for r in calc_rows), 4) if calc_rows else None,
            "rows": rows}
