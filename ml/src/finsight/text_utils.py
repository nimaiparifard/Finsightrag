from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache

_DOC_ID = re.compile(r"^(?P<company>.+?)_(?P<year>\d{4})(?P<q>Q[1-4])?_(?P<form>10K|10Q|8K|EARNINGS)$")


@lru_cache(maxsize=1)
def _encoder() -> Callable[[str], int]:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s, disallowed_special=()))
    except Exception:  # offline / missing BPE file -> rough estimate
        return lambda s: max(1, len(s) // 4)


def count_tokens(text: str) -> int:
    return _encoder()(text)


def parse_doc_id(doc_id: str) -> dict[str, str]:
    """'3M_2018_10K' -> company/year/quarter/form metadata."""
    m = _DOC_ID.match(doc_id)
    if not m:
        return {"company": doc_id.split("_")[0], "year": "", "form": ""}
    form = m["form"].replace("10K", "10-K").replace("10Q", "10-Q").replace("8K", "8-K")
    return {"company": m["company"], "year": m["year"], "quarter": m["q"] or "", "form": form}


def normalize_ws(text: str) -> str:
    """Collapse the one-token-per-line layout PDFs produce for tables."""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


_SUFFIX = re.compile(r"[,\s]+(inc\.?|corp\.?|corporation|co\.?|company|ltd\.?|plc|llc|holdings?|group|& co\.?|/[a-z]{2})\s*$", re.I)


def clean_company_name(title: str) -> str:
    """'Apple Inc.' -> 'Apple', 'JPMorgan Chase & Co' -> 'JPMorgan Chase', 'AMAZON COM INC' -> 'AMAZON COM'."""
    prev = None
    while prev != title:
        prev, title = title, _SUFFIX.sub("", title.strip())
    return title.strip(" ,.")
