from __future__ import annotations

from typing import Any

from finsight.interfaces import Chunk, Page, ParsedDocument
from finsight.text_utils import count_tokens

_SEPARATORS = ["\n\n", "\n", ". ", " "]


def split_text(text: str, max_tokens: int, overlap: int, seps: list[str] | None = None) -> list[str]:
    """Recursive splitter: largest separator first, then pack pieces up to max_tokens."""
    seps = _SEPARATORS if seps is None else seps
    if count_tokens(text) <= max_tokens:
        return [text] if text.strip() else []
    if not seps:  # hard split on characters
        step = max(1, (max_tokens - overlap) * 4)
        return [text[i : i + max_tokens * 4] for i in range(0, len(text), step)]
    sep, rest = seps[0], seps[1:]
    pieces: list[str] = []
    for part in text.split(sep):
        if count_tokens(part) > max_tokens:
            pieces += split_text(part, max_tokens, overlap, rest)
        elif part.strip():
            pieces.append(part)
    chunks: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for piece in pieces:
        t = count_tokens(piece)
        if cur and cur_tok + t > max_tokens:
            chunks.append(sep.join(cur))
            # carry trailing pieces as overlap
            carry: list[str] = []
            carry_tok = 0
            for prev in reversed(cur):
                pt = count_tokens(prev)
                if carry_tok + pt > overlap:
                    break
                carry.insert(0, prev)
                carry_tok += pt
            if not carry and overlap > 0:  # every piece is bigger than the overlap: carry a text tail
                carry = [cur[-1][-overlap * 4 :]]
                carry_tok = count_tokens(carry[0])
            cur, cur_tok = carry, carry_tok
        cur.append(piece)
        cur_tok += t
    if cur:
        chunks.append(sep.join(cur))
    return chunks


def table_chunks(page: Page, doc_meta: dict[str, Any], max_tokens: int) -> list[Chunk]:
    out: list[Chunk] = []
    for tbl in page.tables:
        text = tbl.markdown
        if count_tokens(text) > max_tokens * 3:  # keep huge tables as a header + first rows
            text = "\n".join(text.splitlines()[: max_tokens // 4])
        out.append(
            Chunk(doc_id=page.doc_id, page=page.page, text=text, chunk_type="table", meta=dict(doc_meta))
        )
    return out


class RecursiveChunker:
    """Baseline: split each page independently, so a chunk never straddles pages."""

    def __init__(self, max_tokens: int = 800, overlap_tokens: int = 100, table_chunks: bool = True) -> None:
        self.max_tokens, self.overlap, self.tables = max_tokens, overlap_tokens, table_chunks

    def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        out: list[Chunk] = []
        for page in doc.pages:
            for text in split_text(page.text, self.max_tokens, self.overlap):
                out.append(Chunk(doc.doc_id, page.page, text, meta=dict(doc.meta)))
            if self.tables:
                out += table_chunks(page, doc.meta, self.max_tokens)
        return out
