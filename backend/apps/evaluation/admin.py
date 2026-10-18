from django.contrib import admin

from .models import EvalRun


@admin.register(EvalRun)
class EvalRunAdmin(admin.ModelAdmin):
    list_display = ["config_name", "dataset", "n_questions", "created_at"]
    list_filter = ["dataset", "config_name"]
