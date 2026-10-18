from __future__ import annotations

from finsight.interfaces import DocumentParser


def get_parser(name: str, extract_tables: bool = True) -> DocumentParser:
    if name == "pdf":
        from finsight.ingestion.parsers.pdf_parser import PyMuPDFParser

        return PyMuPDFParser(extract_tables=extract_tables)
    if name == "html":
        from finsight.ingestion.parsers.html_parser import HTMLFilingParser

        return HTMLFilingParser(extract_tables=extract_tables)
    raise ValueError(f"unknown parser '{name}'")
