"""Bootstrap the golden set with an LLM, then a HUMAN verifies it.

Types and target mix (100 questions): factual 30, numeric 25, multi-hop 20, multi-doc 15, unanswerable 10.
Every generated item is written with "verified": false. Only verified items count for gating and reporting;
`load_golden(only_verified=True)` enforces that. Generation is a first draft, not ground truth.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from finsight.interfaces import Chunk, LLMProvider, Message

TARGET_MIX = {"factual": 30, "numeric": 25, "multihop": 20, "multidoc": 15, "unanswerable": 10}
_HAS_NUMBERS = re.compile(r"\d[\d,]{2,}")

SYSTEM = (
    "You write evaluation questions about SEC filings. You are given one or more EXCERPTS. "
    "Write ONE question that can be answered ONLY from the excerpts, with a short exact answer. "
    "Do not mention 'the excerpt' or 'the passage'; name the company and fiscal year in the question. "
    'Reply with JSON only: {"question": "...", "answer": "..."}'
)
KIND_HINT = {
    "factual": "Ask a factual lookup (who/what/where/which), not a number.",
    "numeric": "Ask for a specific number from a table or text (state the unit, e.g. USD millions).",
    "multihop": "Ask something that needs BOTH excerpts (e.g. a change, ratio, or difference between the two numbers).",
    "multidoc": "The excerpts are from two different companies. Ask a comparison between them.",
}


def _ask(llm: LLMProvider, kind: str, chunks: list[Chunk]) -> dict[str, str] | None:
    body = "\n\n".join(f"EXCERPT {i + 1} [{c.doc_id}, page {c.page + 1}]:\n{c.text[:1800]}" for i, c in enumerate(chunks))
    out = llm.generate([Message("system", SYSTEM + " " + KIND_HINT[kind]), Message("user", body)],
                       temperature=0.3, max_tokens=300)
    m = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    if not d or not str(d.get("question", "")).strip() or not str(d.get("answer", "")).strip():
        return None
    return {"question": str(d["question"]).strip(), "answer": str(d["answer"]).strip()}


def generate(llm: LLMProvider, chunks: list[Chunk], mix: dict[str, int] | None = None, seed: int = 7,
             corpus_companies: set[str] | None = None) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    mix = mix or TARGET_MIX
    texty = [c for c in chunks if c.chunk_type == "text" and len(c.text) > 400 and c.meta.get("company")]
    numeric = [c for c in chunks if len(_HAS_NUMBERS.findall(c.text)) >= 6 and c.meta.get("company")]
    by_doc: dict[str, list[Chunk]] = {}
    for c in numeric:
        by_doc.setdefault(c.doc_id, []).append(c)
    by_company: dict[str, list[Chunk]] = {}
    for c in numeric:
        by_company.setdefault(str(c.meta["company"]), []).append(c)

    items: list[dict[str, Any]] = []

    def add(kind: str, srcs: list[Chunk], qa: dict[str, str] | None) -> None:
        if not qa:
            return
        items.append({"id": f"g{len(items) + 1:03d}", "type": kind, "question": qa["question"], "answer": qa["answer"],
                      "evidence": [{"doc_id": c.doc_id, "page": c.page} for c in srcs], "verified": False})

    def sample(pool: list[Chunk], n: int) -> list[Chunk]:
        return rng.sample(pool, min(n, len(pool)))

    for kind, n in mix.items():
        made, tries = 0, 0
        while made < n and tries < n * 6:
            tries += 1
            before = len(items)
            if kind == "factual" and texty:
                c = rng.choice(texty)
                add(kind, [c], _ask(llm, kind, [c]))
            elif kind == "numeric" and numeric:
                c = rng.choice(numeric)
                add(kind, [c], _ask(llm, kind, [c]))
            elif kind == "multihop" and by_doc:
                docs = [d for d, cs in by_doc.items() if len(cs) >= 2]
                if docs:
                    cs = sample(by_doc[rng.choice(docs)], 2)
                    add(kind, cs, _ask(llm, kind, cs))
            elif kind == "multidoc" and len(by_company) >= 2:
                a, b = rng.sample(sorted(by_company), 2)
                cs = [rng.choice(by_company[a]), rng.choice(by_company[b])]
                add(kind, cs, _ask(llm, kind, cs))
            elif kind == "unanswerable":
                # questions about things provably absent: a made-up fiscal year / an unknown company / non-financial trivia
                src = rng.choice(texty) if texty else None
                if src:
                    year = rng.choice(["2031", "2035"])
                    items.append({"id": f"g{len(items) + 1:03d}", "type": kind, "verified": False, "evidence": [],
                                  "question": rng.choice([
                                      f"What was {src.meta['company']}'s operating income in fiscal {year}?",
                                      f"What was the CEO's total compensation at {src.meta['company']} in fiscal {year}?",
                                      f"How many stores will {src.meta['company']} open in {year}?",
                                      "What is the capital of Australia?"]),
                                  "answer": "Not found in the provided documents."})
            made += len(items) - before
    return items


def write_jsonl(items: list[dict[str, Any]], path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(i) for i in items) + "\n", encoding="utf-8")


def summary(path: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    types: dict[str, int] = {}
    for r in rows:
        types[r["type"]] = types.get(r["type"], 0) + 1
    return {"total": len(rows), "verified": sum(r.get("verified", False) for r in rows), "by_type": types}
