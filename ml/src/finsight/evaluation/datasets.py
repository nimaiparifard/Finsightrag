"""Loaders that turn benchmark files into one common record: EvalItem."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalItem:
    id: str
    question: str
    answer: str
    evidence: list[tuple[str, int]] = field(default_factory=list)  # (doc_id, 0-indexed page)
    qtype: str = ""
    answerable: bool = True

    @property
    def gold(self) -> set[tuple[str, int]]:
        return set(self.evidence)


def load_financebench(root: str = "data/raw/financebench") -> list[EvalItem]:
    path = Path(root) / "data" / "financebench_open_source.jsonl"
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        ev = [(e["doc_name"], int(e["evidence_page_num"])) for e in r["evidence"]]
        items.append(EvalItem(r["financebench_id"], r["question"], r["answer"], ev, r["question_type"]))
    return items


def financebench_pdfs(root: str = "data/raw/financebench", doc_ids: set[str] | None = None) -> dict[str, str]:
    pdfs = {p.stem: str(p) for p in sorted((Path(root) / "pdfs").glob("*.pdf"))}
    return {d: p for d, p in pdfs.items() if doc_ids is None or d in doc_ids}


def load_golden(path: str = "ml/eval/golden_set.jsonl", only_verified: bool = True) -> list[EvalItem]:
    """{"id","question","answer","evidence":[{"doc_id","page"}],"type"}; type 'unanswerable' must be refused."""
    items = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if only_verified and not r.get("verified", False):
            continue  # LLM-drafted items are not ground truth until a human has checked them
        ev = [(e["doc_id"], int(e["page"])) for e in r.get("evidence", [])]
        items.append(EvalItem(r["id"], r["question"], r["answer"], ev, r.get("type", ""),
                              answerable=r.get("type") != "unanswerable"))
    return items
