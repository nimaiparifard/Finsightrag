"""Post-generation checks: citations must exist in context, numbers must be grounded."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from finsight.interfaces import Hit

NOT_FOUND = "Not found in the provided documents."
_CITATION = re.compile(r"\[([^\[\]:]+):(\d+)\]")
# anything shaped like a citation (id:something) that the strict pattern above does not accept
_CITATION_LIKE = re.compile(r"\[[^\[\]\s]+:[^\[\]]+\]")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def parse_citations(text: str) -> list[tuple[str, int]]:
    return [(m[1].strip(), int(m[2])) for m in _CITATION.finditer(text)]


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUMBER.findall(text):
        n = m.replace(",", "").rstrip(".")
        out.add(n)
        out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return out


@dataclass
class GuardrailReport:
    ok: bool = True
    invalid_citations: list[tuple[str, int]] = field(default_factory=list)
    malformed_citations: list[str] = field(default_factory=list)
    no_citations: bool = False
    uncited_sentences: list[str] = field(default_factory=list)
    ungrounded_numbers: list[str] = field(default_factory=list)


# constants a calculation may legitimately introduce (percent, per-year/quarter, thousands ...)
CALC_CONSTANTS = {"100", "1000", "12", "4", "2", "365", "1000000"}


def check_answer(answer: str, hits: list[Hit], calc_values: list[float] | None = None,
                 calc_exprs: list[str] | None = None) -> GuardrailReport:
    """calc_exprs: rendered 'expr = result' strings. Their operands must come from the context
    (or be a common constant); the strings are then excluded from the free-text number check."""
    rep = GuardrailReport()
    if answer.strip() == NOT_FOUND:
        return rep
    ctx_numbers: set[str] = set()
    for h in hits:
        ctx_numbers |= _numbers(h.chunk.text)
    for rendered in calc_exprs or []:
        expr = rendered.rsplit(" = ", 1)[0]
        answer = answer.replace(rendered, "")
        for n in _numbers(expr):
            if n not in ctx_numbers and n not in CALC_CONSTANTS and not _derived(n, ctx_numbers):
                rep.ungrounded_numbers.append(n)
    available = {(h.chunk.doc_id, h.chunk.page) for h in hits}
    cites = parse_citations(answer)
    for cit in cites:
        if cit not in available:
            rep.invalid_citations.append(cit)
    valid = [c for c in cites if c in available]
    strict = {m.group(0) for m in _CITATION.finditer(answer)}
    rep.malformed_citations = [m.group(0) for m in _CITATION_LIKE.finditer(answer) if m.group(0) not in strict]
    rep.no_citations = not valid  # a grounded answer must cite at least one page that was actually retrieved

    body = _CITATION.sub("", answer)
    for sent in re.split(r"(?<=[.!?])\s+", answer):
        if _NUMBER.search(sent) and not _CITATION.search(sent) and len(sent) > 25:
            rep.uncited_sentences.append(sent.strip())

    grounded = set()
    for h in hits:
        grounded |= _numbers(h.chunk.text)
    for v in calc_values or []:
        grounded |= _numbers(f"{v:.6f}".rstrip("0")) | _numbers(f"{v:,.2f}") | _numbers(f"{v:.1f}") | _numbers(f"{v:.0f}")
    for n in _numbers(body):
        if n not in grounded and not _is_year_or_small(n) and not _derived(n, grounded):
            rep.ungrounded_numbers.append(n)
    rep.ok = not (rep.invalid_citations or rep.malformed_citations or rep.no_citations or rep.ungrounded_numbers)
    return rep


def _is_year_or_small(n: str) -> bool:
    try:
        v = float(n)
    except ValueError:
        return True
    return 1990 <= v <= 2100 or v < 10  # years, list indices, small counts


def _derived(n: str, grounded: set[str]) -> bool:
    """Allow rounded forms of grounded numbers (e.g. 383.3 for 383285 'in millions' → billions)."""
    try:
        v = float(n)
    except ValueError:
        return False
    for g in grounded:
        try:
            gv = float(g)
        except ValueError:
            continue
        for scale in (1, 1e3, 1e6, 1e-3, 1e-6):
            if gv and abs(gv * scale - v) / abs(gv * scale) < 0.006:
                return True
    return False
