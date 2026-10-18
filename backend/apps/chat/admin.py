from django.contrib import admin

from .models import Conversation, Feedback, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "title", "updated_at"]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "role", "refused", "cached", "latency_s", "created_at"]
    list_filter = ["role", "refused", "cached"]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["message", "thumbs_up", "reviewed", "created_at"]
    list_filter = ["thumbs_up", "reviewed"]
