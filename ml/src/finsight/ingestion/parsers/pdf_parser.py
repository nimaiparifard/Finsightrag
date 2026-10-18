from __future__ import annotations

import fitz  # PyMuPDF

from finsight.interfaces import Page, ParsedDocument, Table
from finsight.text_utils import normalize_ws, parse_doc_id


class PyMuPDFParser:
    """Page-faithful PDF parser; tables are pulled out separately as Markdown + rows."""

    def __init__(self, extract_tables: bool = True) -> None:
        self.extract_tables = extract_tables

    def parse(self, path: str, doc_id: str) -> ParsedDocument:
        pages: list[Page] = []
        with fitz.open(path) as pdf:
            for i, pg in enumerate(pdf):
                tables = self._tables(pg, i) if self.extract_tables else []
                pages.append(Page(doc_id=doc_id, page=i, text=normalize_ws(pg.get_text("text")), tables=tables))
        return ParsedDocument(doc_id=doc_id, pages=pages, meta=parse_doc_id(doc_id))

    @staticmethod
    def _tables(pg: fitz.Page, index: int) -> list[Table]:
        out: list[Table] = []
        try:
            found = pg.find_tables()
        except Exception:
            return out
        for t in found.tables:
            rows = [[(c or "").strip() for c in row] for row in t.extract()]
            rows = [r for r in rows if any(r)]
            if len(rows) < 2 or max(len(r) for r in rows) < 2:
                continue
            out.append(Table(page=index, markdown=rows_to_markdown(rows), rows=rows))
        return out


def rows_to_markdown(rows: list[list[str]]) -> str:
    width = max(len(r) for r in rows)
    norm = [[c.replace("\n", " ").replace("|", "/") for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(lines)
