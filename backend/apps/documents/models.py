from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Company(TimeStampedModel):
    ticker = models.CharField(max_length=12, unique=True)
    cik = models.CharField(max_length=10, blank=True)
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["ticker"]
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return f"{self.ticker} ({self.name})"


class Filing(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        DOWNLOADED = "downloaded"
        INDEXED = "indexed"
        FAILED = "failed"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="filings")
    form = models.CharField(max_length=8)  # 10-K / 10-Q
    fiscal_year = models.PositiveSmallIntegerField()
    period_end = models.DateField(null=True, blank=True)
    accession = models.CharField(max_length=24, unique=True)
    doc_id = models.CharField(max_length=64, unique=True)  # key used in the vector index and in citations
    source_url = models.URLField(max_length=500, blank=True)
    storage_path = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    chunk_count = models.PositiveIntegerField(default=0)
    index_version = models.PositiveIntegerField(default=0)  # bumped when the filing is re-indexed
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["company__ticker", "-fiscal_year", "form"]

    def __str__(self) -> str:
        return self.doc_id


class IngestionJob(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                     related_name="ingestion_jobs")
    params = models.JSONField(default=dict)  # {ticker, years: [from, to], forms: [...]}
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    total = models.PositiveIntegerField(default=0)
    done = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    @property
    def progress(self) -> int:
        if self.status == self.Status.DONE:
            return 100
        return int(100 * (self.done + self.failed) / self.total) if self.total else 0
