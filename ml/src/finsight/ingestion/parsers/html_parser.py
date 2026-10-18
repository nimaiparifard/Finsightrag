from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import NavigableString

from finsight.ingestion.parsers.pdf_parser import rows_to_markdown
from finsight.interfaces import Page, ParsedDocument, Table
from finsight.text_utils import normalize_ws, parse_doc_id

# EDGAR HTML has no real pages. We emulate them by splitting on explicit page-break
# styles; if none exist, on a fixed character budget so citations stay usable.
_PAGE_BREAK = re.compile(r"page-break-(?:before|after)\s*:\s*always", re.I)
_FALLBACK_PAGE_CHARS = 4500


class HTMLFilingParser:
    def __init__(self, extract_tables: bool = True) -> None:
        self.extract_tables = extract_tables

    def parse(self, path: str, doc_id: str) -> ParsedDocument:
        with open(path, "rb") as f:
            soup = BeautifulSoup(f.read(), "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
            tag.decompose()  # inline-XBRL header blob

        # mark page breaks, then walk the body in order
        for el in soup.find_all(style=_PAGE_BREAK):
            el.insert_before("\x0c")
        tables_by_marker: dict[str, Table] = {}
        for n, tbl in enumerate(soup.find_all("table")):
            rows = _table_rows(tbl)
            if self.extract_tables and len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                marker = f"\x01T{n}\x01"
                tables_by_marker[marker] = Table(page=-1, markdown=rows_to_markdown(rows), rows=rows)
                tbl.replace_with(NavigableString(marker + "\n" + "\n".join(" ".join(r) for r in rows)))
            else:
                tbl.replace_with(NavigableString("\n".join(" ".join(r) for r in rows)))

        text = soup.get_text("\n")
        raw_pages = [p for p in text.split("\x0c") if p.strip()]
        if len(raw_pages) <= 1:
            raw_pages = _split_by_size(text, _FALLBACK_PAGE_CHARS)

        pages: list[Page] = []
        for i, raw in enumerate(raw_pages):
            tables = []
            for marker, found in tables_by_marker.items():
                if marker in raw:
                    tables.append(Table(page=i, markdown=found.markdown, rows=found.rows))
                    raw = raw.replace(marker, "")
            pages.append(Page(doc_id=doc_id, page=i, text=normalize_ws(raw), tables=tables))
        return ParsedDocument(doc_id=doc_id, pages=pages, meta=parse_doc_id(doc_id))


def _table_rows(tbl) -> list[list[str]]:  # type: ignore[no-untyped-def]
    rows: list[list[str]] = []
    for tr in tbl.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = _merge_currency_cells(cells)
        if any(cells):
            rows.append(cells)
    return rows


def _merge_currency_cells(cells: list[str]) -> list[str]:
    """EDGAR splits '$', '1,234' and ')' into separate cells; glue them back and drop blanks."""
    out: list[str] = []
    for c in cells:
        if not c:
            continue
        if out and c in {")", "%", ")%"}:
            out[-1] += c
        elif out and out[-1] in {"$", "(", "($"}:
            out[-1] += c
        else:
            out.append(c)
    return out


def _split_by_size(text: str, size: int) -> list[str]:
    paras, pages, cur = text.split("\n"), [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            pages.append(cur)
            cur = ""
        cur += p + "\n"
    if cur.strip():
        pages.append(cur)
    return pages
