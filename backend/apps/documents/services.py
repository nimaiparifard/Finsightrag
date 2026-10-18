"""WRITE logic. Celery tasks and views stay thin and call these."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from django.conf import settings

from apps.core.exceptions import DomainError

from .models import Company, Filing, IngestionJob

log = logging.getLogger(__name__)

ALLOWED_FORMS = {"10-K", "10-Q"}


class Indexer(Protocol):
    def __call__(self, doc_id: str, path: str, meta: dict[str, Any]) -> int:
        """Parse + chunk + embed + index one filing; returns the number of chunks."""


def create_ingestion_job(user, ticker: str, years: tuple[int, int], forms: list[str]) -> IngestionJob:  # type: ignore[no-untyped-def]
    ticker = ticker.strip().upper()
    if not ticker.isalnum() or len(ticker) > 12:
        raise DomainError("Invalid ticker.")
    bad = set(forms) - ALLOWED_FORMS
    if bad or not forms:
        raise DomainError(f"forms must be a non-empty subset of {sorted(ALLOWED_FORMS)}")
    if years[0] > years[1] or years[1] - years[0] > 10:
        raise DomainError("years must be an ascending range of at most 10 years.")
    job = IngestionJob.objects.create(
        requested_by=user, params={"ticker": ticker, "years": list(years), "forms": sorted(forms)})
    from .tasks import run_ingestion_job

    run_ingestion_job.delay(str(job.id))
    return job


def default_indexer() -> Indexer:
    """Calls the ml package directly (it never imports Django). Heavy imports stay lazy: web workers don't need them."""

    def index(doc_id: str, path: str, meta: dict[str, Any]) -> int:
        from finsight import registry
        from finsight.config import Config
        from finsight.ingestion.pipeline import ingest

        cfg = Config.load(settings.FINSIGHT_CONFIG)
        embedder = registry.create("embedder", cfg.embedder.name, **cfg.embedder.params)
        store = ingest(cfg, {doc_id: path}, embedder, meta={doc_id: meta})
        return sum(1 for c in store.chunks if c.doc_id == doc_id)

    return index


def default_edgar():  # type: ignore[no-untyped-def]
    from finsight.ingestion.edgar_client import EdgarClient

    return EdgarClient()


def run_job(job_id: str, edgar=None, indexer: Indexer | None = None,  # type: ignore[no-untyped-def]
            raw_dir: str | None = None) -> IngestionJob:
    from finsight.ingestion.edgar_client import EdgarError
    from finsight.text_utils import clean_company_name

    job = IngestionJob.objects.get(pk=job_id)
    job.status = IngestionJob.Status.RUNNING
    job.save(update_fields=["status", "updated_at"])
    p = job.params
    raw = Path(raw_dir or Path(settings.FINSIGHT_DATA_DIR) / "raw" / "edgar")
    try:
        edgar = edgar or default_edgar()
        refs = edgar.list_filings(p["ticker"], tuple(p["forms"]), tuple(p["years"]))
    except EdgarError as e:
        return _fail(job, str(e))
    except Exception as e:  # network etc.
        log.exception("edgar listing failed")
        return _fail(job, f"EDGAR request failed: {e}")
    if not refs:
        return _fail(job, "No matching filings found on EDGAR.")

    cik, title = refs[0].cik, refs[0].company
    company, _ = Company.objects.update_or_create(ticker=p["ticker"], defaults={"cik": cik, "name": title})
    job.total = len(refs)
    job.save(update_fields=["total", "updated_at"])
    indexer = indexer or default_indexer()
    meta = {"company": clean_company_name(title), "ticker": p["ticker"], "cik": cik}

    for ref in refs:
        filing, _ = Filing.objects.update_or_create(
            accession=ref.accession,
            defaults={"company": company, "form": ref.form, "fiscal_year": ref.fiscal_year,
                      "period_end": ref.report_date or None, "doc_id": ref.doc_id, "source_url": ref.url})
        if filing.status == Filing.Status.INDEXED:  # idempotent: nothing to do
            job.done += 1
            job.save(update_fields=["done", "updated_at"])
            continue
        try:
            path = edgar.download(ref, raw)
            filing.storage_path, filing.status = str(path), Filing.Status.DOWNLOADED
            filing.save(update_fields=["storage_path", "status", "updated_at"])
            n = indexer(ref.doc_id, str(path), {**meta, "year": str(ref.fiscal_year), "form": ref.form})
            filing.status, filing.chunk_count, filing.error = Filing.Status.INDEXED, n, ""
            filing.index_version += 1
            job.done += 1
        except Exception as e:
            log.exception("filing %s failed", ref.doc_id)
            filing.status, filing.error = Filing.Status.FAILED, str(e)[:2000]
            job.failed += 1
        filing.save()
        job.save(update_fields=["done", "failed", "updated_at"])

    job.status = IngestionJob.Status.DONE if job.done else IngestionJob.Status.FAILED
    if not job.done:
        job.error = "Every filing failed; see the filing errors."
    job.save()
    if job.done:
        _notify_reload()
    return job


def _fail(job: IngestionJob, message: str) -> IngestionJob:
    job.status, job.error = IngestionJob.Status.FAILED, message
    job.save()
    return job


def _notify_reload(post: Callable[..., Any] | None = None) -> None:
    """Tell the serving process to reload the index. Best effort: ingestion succeeded either way."""
    try:
        import httpx

        headers = {"X-Admin-Token": settings.SERVING_ADMIN_TOKEN} if settings.SERVING_ADMIN_TOKEN else {}
        (post or httpx.post)(f"{settings.SERVING_URL}/v1/admin/reload", headers=headers, timeout=10)
    except Exception:
        log.warning("serving reload failed; restart serving to pick up new filings")



DOC_ID_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,64}$")


def resolve_document_path(doc_id: str) -> Path:
    """Source file for a doc_id: an ingested EDGAR filing, else a bundled FinanceBench PDF.
    doc_id is validated and the result must stay inside the data dir (no path traversal)."""
    from apps.core.exceptions import NotFoundInIndex

    if not DOC_ID_RE.match(doc_id):
        raise NotFoundInIndex("Unknown document.")
    data = Path(settings.FINSIGHT_DATA_DIR).resolve()
    candidates = []
    f = Filing.objects.filter(doc_id=doc_id).exclude(storage_path="").first()
    if f:
        candidates.append(Path(f.storage_path))
    candidates.append(data / "raw" / "financebench" / "pdfs" / f"{doc_id}.pdf")
    for c in candidates:
        c = c.resolve()
        if c.is_file() and data in c.parents:
            return c
    raise NotFoundInIndex("Unknown document.")


def read_page_text(doc_id: str, page: int) -> dict:
    """Text (and tables) of one page from the parse cache written during ingestion."""
    import json

    from apps.core.exceptions import NotFoundInIndex

    if not DOC_ID_RE.match(doc_id):
        raise NotFoundInIndex("Unknown document.")
    root = Path(settings.FINSIGHT_DATA_DIR) / "interim" / "parsed"
    for kind in ("pdf", "html"):
        f = root / kind / f"{doc_id}.json"
        if f.is_file():
            pages = json.loads(f.read_text(encoding="utf-8"))["pages"]
            if not 0 <= page < len(pages):
                raise NotFoundInIndex("Page out of range.")
            pg = pages[page]
            return {"doc_id": doc_id, "page": page, "page_count": len(pages), "text": pg["text"],
                    "tables": [t["markdown"] for t in pg["tables"]], "kind": kind}
    raise NotFoundInIndex("Document has not been parsed.")
