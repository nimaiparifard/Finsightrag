import pytest

from finsight.ingestion.edgar_client import EdgarClient, EdgarError, FilingRef


class FakeResp:
    def __init__(self, payload=None, content=b"", status=200):
        self.payload, self.content, self.status_code = payload, content, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        assert self.status_code < 400


class FakeSession:
    def __init__(self):
        self.headers, self.urls = {}, []

    def get(self, url, timeout=0):
        self.urls.append(url)
        if url.endswith("company_tickers.json"):
            return FakeResp({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
        if "submissions/CIK0000320193.json" in url:
            return FakeResp({"filings": {"recent": {
                "form": ["10-K", "10-Q", "10-K", "8-K"], "reportDate": ["2023-09-30", "2023-07-01", "2022-09-24", ""],
                "accessionNumber": ["0000320193-23-000106", "0000320193-23-000077", "0000320193-22-000108", "x"],
                "primaryDocument": ["aapl-20230930.htm", "aapl-20230701.htm", "aapl-20220924.htm", "x.htm"],
                "filingDate": ["2023-11-03", "2023-08-04", "2022-10-28", "2023-01-01"]}, "files": []}})
        return FakeResp(content=b"<html>filing</html>")


def client():
    return EdgarClient("Test User test@example.com", FakeSession(), sleep=lambda s: None)


def test_user_agent_is_required(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(EdgarError, match="User-Agent"):
        EdgarClient()


def test_list_filings_filters_form_and_year():
    c = client()
    refs = c.list_filings("aapl", ("10-K",), years=(2023, 2023))
    assert [r.accession for r in refs] == ["0000320193-23-000106"]
    assert c.s.headers["User-Agent"] == "Test User test@example.com"
    both = c.list_filings("AAPL", ("10-K", "10-Q"))
    assert [r.form for r in both] == ["10-K", "10-Q", "10-K"]  # 8-K without reportDate dropped


def test_doc_ids_and_url():
    r = FilingRef("AAPL", "0000320193", "Apple", "10-Q", "0000320193-23-000077", "a.htm", "2023-07-01", "2023-08-04")
    assert r.doc_id == "AAPL_2023Q3_10Q"
    assert r.url == "https://www.sec.gov/Archives/edgar/data/320193/000032019323000077/a.htm"
    jan = FilingRef("NVDA", "0001045810", "NVIDIA", "10-K", "a", "n.htm", "2024-01-28", "2024-02-21")
    assert jan.fiscal_year == 2023  # period ending late January belongs to the prior fiscal-year label


def test_download_is_idempotent(tmp_path):
    c = client()
    ref = c.list_filings("AAPL", ("10-K",))[0]
    p = c.download(ref, tmp_path)
    n = len(c.s.urls)
    assert p.read_bytes().startswith(b"<html>") and c.download(ref, tmp_path) == p
    assert len(c.s.urls) == n  # second call made no request
    with pytest.raises(EdgarError):
        c.cik_for("ZZZZ")
