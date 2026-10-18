"""Register the documents already present in the vector index as Company/Filing rows (so the Library page and the
company filter show them). Idempotent."""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.documents.models import Company, Filing


class Command(BaseCommand):
    help = "Create Company/Filing rows for every document in the configured index."

    def handle(self, *args, **opts):  # type: ignore[no-untyped-def]
        from finsight.config import Config
        from finsight.store_factory import open_store

        cfg = Config.load(settings.FINSIGHT_CONFIG)
        store = open_store(cfg, dim=None if cfg.store.backend == "numpy" else 768, create=False)
        per_doc: dict[str, dict] = {}
        for c in store.chunks:
            d = per_doc.setdefault(c.doc_id, {"meta": c.meta, "n": 0})
            d["n"] += 1
        made = 0
        for doc_id, d in sorted(per_doc.items()):
            m = d["meta"]
            name = m.get("company") or doc_id.split("_")[0]
            company, _ = Company.objects.get_or_create(ticker=name[:12].upper(), defaults={"name": name})
            _, created = Filing.objects.update_or_create(
                doc_id=doc_id,
                defaults={"company": company, "form": m.get("form") or "10-K",
                          "fiscal_year": int(m.get("year") or 0), "accession": doc_id,
                          "status": Filing.Status.INDEXED, "chunk_count": d["n"]})
            made += created
        self.stdout.write(f"{len(per_doc)} documents, {made} new filings, {Company.objects.count()} companies")
