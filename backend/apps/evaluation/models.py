from django.db import models

from apps.core.models import TimeStampedModel


class EvalRun(TimeStampedModel):
    """One evaluation of one pipeline config. Imported from ml's data/processed/eval/*.json."""

    config_name = models.CharField(max_length=80)
    dataset = models.CharField(max_length=40, default="financebench")
    n_questions = models.PositiveIntegerField()
    metrics = models.JSONField(default=dict)
    git_sha = models.CharField(max_length=40, blank=True)
    source_file = models.CharField(max_length=300, blank=True)
    source_mtime = models.FloatField(default=0)  # re-import only when the file changed

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["source_file", "source_mtime"], name="uniq_eval_source")]

    def __str__(self) -> str:
        return f"{self.config_name} ({self.n_questions}q)"
