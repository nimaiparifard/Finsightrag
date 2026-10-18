"""READ logic."""

from django.db.models import Count, QuerySet

from .models import Company, Filing, IngestionJob


def companies() -> QuerySet[Company]:
    return Company.objects.annotate(filing_count=Count("filings"))


def filings(ticker: str | None = None, form: str | None = None, status: str | None = None) -> QuerySet[Filing]:
    qs = Filing.objects.select_related("company")
    if ticker:
        qs = qs.filter(company__ticker__iexact=ticker)
    if form:
        qs = qs.filter(form=form)
    if status:
        qs = qs.filter(status=status)
    return qs


def jobs_for(user) -> QuerySet[IngestionJob]:  # type: ignore[no-untyped-def]
    return IngestionJob.objects.all() if user.is_staff else IngestionJob.objects.filter(requested_by=user)
