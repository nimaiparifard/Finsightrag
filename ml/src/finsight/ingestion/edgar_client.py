"""SEC EDGAR client. Rules from the SEC: a descriptive User-Agent with contact info, <= 10 requests/second."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

_MIN_INTERVAL = 0.15  # ~6-7 req/s, safely under the 10/s limit


class EdgarError(RuntimeError):
    pass


@dataclass(frozen=True)
class FilingRef:
    ticker: str
    cik: str  # zero-padded 10 digits
    company: str
    form: str
    accession: str
    primary_document: str
    report_date: str  # period end, YYYY-MM-DD
    filing_date: str

    @property
    def fiscal_year(self) -> int:
        """10-K period ends in Jan/Feb belong to the prior fiscal year label used by most companies."""
        y, m = int(self.report_date[:4]), int(self.report_date[5:7])
        return y - 1 if m <= 2 and self.form == "10-K" else y

    @property
    def url(self) -> str:
        return (f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/"
                f"{self.accession.replace('-', '')}/{self.primary_document}")

    @property
    def doc_id(self) -> str:
        q = ""
        if self.form == "10-Q":
            q = f"Q{(int(self.report_date[5:7]) - 1) // 3 + 1}"
        return f"{self.ticker}_{self.fiscal_year}{q}_{self.form.replace('-', '')}"


class EdgarClient:
    def __init__(self, user_agent: str | None = None, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        ua = user_agent or os.environ.get("SEC_USER_AGENT", "")
        if "@" not in ua:
            raise EdgarError('SEC requires a User-Agent with contact info: set SEC_USER_AGENT="Your Name you@email"')
        self.s = session or requests.Session()
        self.s.headers["User-Agent"] = ua
        self._sleep, self._last, self._lock = sleep, 0.0, threading.Lock()
        self._tickers: dict[str, tuple[str, str]] | None = None

    def _get(self, url: str) -> requests.Response:
        with self._lock:  # serialize so concurrent callers still respect the global rate
            wait = _MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
        for attempt in range(3):
            r = self.s.get(url, timeout=60)
            if r.status_code in (429, 503):
                self._sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        raise EdgarError(f"EDGAR kept throttling: {url}")

    def cik_for(self, ticker: str) -> tuple[str, str]:
        if self._tickers is None:
            data = self._get("https://www.sec.gov/files/company_tickers.json").json()
            self._tickers = {v["ticker"].upper(): (str(v["cik_str"]).zfill(10), v["title"]) for v in data.values()}
        try:
            return self._tickers[ticker.upper()]
        except KeyError:
            raise EdgarError(f"unknown ticker '{ticker}'") from None

    def list_filings(self, ticker: str, forms: tuple[str, ...] = ("10-K",),
                     years: tuple[int, int] | None = None) -> list[FilingRef]:
        """years = (first, last) fiscal year inclusive. Older filings live in extra files listed under 'files'."""
        cik, title = self.cik_for(ticker)
        sub = self._get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        blocks = [sub["filings"]["recent"]]
        for extra in sub["filings"].get("files", []):
            blocks.append(self._get(f"https://data.sec.gov/submissions/{extra['name']}").json())
        out: list[FilingRef] = []
        for b in blocks:
            for i, form in enumerate(b["form"]):
                if form not in forms or not b["reportDate"][i]:
                    continue
                ref = FilingRef(ticker.upper(), cik, title, form, b["accessionNumber"][i], b["primaryDocument"][i],
                                b["reportDate"][i], b["filingDate"][i])
                if years is None or years[0] <= ref.fiscal_year <= years[1]:
                    out.append(ref)
        return sorted(out, key=lambda r: r.report_date, reverse=True)

    def download(self, ref: FilingRef, dest_dir: str | Path) -> Path:
        dest = Path(dest_dir) / ref.ticker / f"{ref.doc_id}.htm"
        if dest.exists():
            return dest  # idempotent
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(self._get(ref.url).content)
        tmp.replace(dest)
        return dest
