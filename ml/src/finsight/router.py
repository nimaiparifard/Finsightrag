"""Query understanding: which company/year is the user asking about, and what kind of question."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from finsight.interfaces import LLMProvider, Message

QUESTION_TYPES = ("lookup", "numeric", "comparison", "out_of_scope")


@dataclass
class Route:
    filters: dict[str, Any] = field(default_factory=dict)
    qtype: str = "lookup"


def heuristic_route(question: str, companies: set[str]) -> Route:
    """No LLM: match known company names in the question. Longest names first ('Johnson & Johnson')."""
    found = [c for c in sorted(companies, key=len, reverse=True)
             if re.search(rf"(?<!\w){re.escape(c)}(?!\w)", question, re.I)]
    # drop names contained in a longer match
    found = [c for c in found if not any(c != o and c.lower() in o.lower() for o in found)]
    qtype = "comparison" if re.search(r"\b(compare|versus|vs\.?|difference between)\b", question, re.I) else (
        "numeric" if re.search(r"\b(what (was|is|were)|how much|ratio|margin|growth|percent|%)\b", question, re.I)
        else "lookup")
    return Route({"company": found} if found else {}, qtype)


def llm_route(llm: LLMProvider, question: str, companies: set[str]) -> Route:
    system = ("Extract search filters from a question about SEC filings. Reply with JSON only: "
              '{"company": [<names from the list or empty>], "year": [<fiscal years or empty>], '
              '"form": "10-K"|"10-Q"|null, "type": "lookup"|"numeric"|"comparison"|"out_of_scope"}. '
              f"Known companies: {sorted(companies)}")
    out = llm.generate([Message("system", system), Message("user", question)], temperature=0.0, max_tokens=200)
    try:
        m = re.search(r"\{.*\}", out, re.S)
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return heuristic_route(question, companies)
    filters: dict[str, Any] = {}
    names = [c for c in data.get("company") or [] if c in companies]
    if names:
        filters["company"] = names
    if data.get("year"):
        filters["year"] = [str(y) for y in data["year"]]
    if data.get("form"):
        filters["form"] = data["form"]
    qtype = str(data["type"]) if data.get("type") in QUESTION_TYPES else "lookup"
    return Route(filters, qtype)
