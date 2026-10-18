from __future__ import annotations

import re

from finsight.ingestion.chunkers.recursive import split_text, table_chunks
from finsight.interfaces import Chunk, ParsedDocument

# "Item 1A. Risk Factors", "ITEM 7 - MANAGEMENT'S DISCUSSION ..." at the start of a line.
_ITEM = re.compile(r"^\s*item\s+(\d{1,2}[A-C]?)\s*[.:\-–—]?\s*(.{0,80})$", re.I | re.M)
_ITEM_NAMES = {
    "1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments", "2": "Properties",
    "3": "Legal Proceedings", "5": "Market for Registrant's Common Equity",
    "7": "MD&A", "7A": "Market Risk Disclosures", "8": "Financial Statements",
    "9A": "Controls and Procedures",
}


class SectionChunker:
    """Respects Item boundaries: a chunk never spans two sections, and carries its section name."""

    def __init__(self, max_tokens: int = 800, overlap_tokens: int = 100, table_chunks: bool = True) -> None:
        self.max_tokens, self.overlap, self.tables = max_tokens, overlap_tokens, table_chunks

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        out: list[Chunk] = []
        section = "Front Matter"
        for page in doc.pages:
            # split the page at every Item heading; text before the first heading stays in `section`
            pos, segments = 0, []
            for m in _ITEM.finditer(page.text):
                if _looks_like_toc(page.text, m):
                    continue
                segments.append((section, page.text[pos : m.start()]))
                section, pos = _section_name(m), m.start()
            segments.append((section, page.text[pos:]))
            for sec, text in segments:
                for piece in split_text(text, self.max_tokens, self.overlap):
                    out.append(Chunk(doc.doc_id, page.page, piece, section=sec, meta=dict(doc.meta)))
            if self.tables:
                for c in table_chunks(page, doc.meta, self.max_tokens):
                    c.section = section
                    out.append(c)
        return out


def _section_name(m: re.Match[str]) -> str:
    num = m[1].upper()
    name = _ITEM_NAMES.get(num) or m[2].strip().title()
    return f"Item {num} {name}".strip()


def _looks_like_toc(text: str, m: re.Match[str]) -> bool:
    """Table-of-contents rows end in a page number; real headings don't."""
    return bool(re.search(r"\s\d{1,3}\s*$", m[0])) and text.count("Item") > 8
