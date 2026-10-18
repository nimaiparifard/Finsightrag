from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Watchlist(TimeStampedModel):
    """A user-defined document set ('my watchlist') that can be used as a chat filter."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watchlists")
    name = models.CharField(max_length=100)
    companies = models.ManyToManyField("documents.Company", blank=True, related_name="watchlists")

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_watchlist_name_per_owner")]

    def __str__(self) -> str:
        return self.name
