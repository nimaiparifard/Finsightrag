from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Conversation(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    title = models.CharField(max_length=200, blank=True)
    filters = models.JSONField(default=dict, blank=True)  # default company/year/form filters for the thread

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title or str(self.id)


class Message(TimeStampedModel):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    citations = models.JSONField(default=list, blank=True)  # [{"doc_id", "page"}]
    chunks = models.JSONField(default=list, blank=True)  # retrieved chunks + scores, for the debug drawer
    latency_s = models.FloatField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    usage = models.JSONField(default=dict, blank=True)
    cached = models.BooleanField(default=False)
    refused = models.BooleanField(default=False)
    guardrails = models.JSONField(null=True, blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)  # which prompt file produced this answer
    trace_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["created_at"]


class Feedback(TimeStampedModel):
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="feedback")
    thumbs_up = models.BooleanField()
    comment = models.TextField(blank=True)
    reviewed = models.BooleanField(default=False)  # set once a human has vetted it for the golden set
