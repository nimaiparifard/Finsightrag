from django.contrib import admin

from .models import Company, Filing, IngestionJob


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["ticker", "name", "cik"]
    search_fields = ["ticker", "name"]


@admin.register(Filing)
class FilingAdmin(admin.ModelAdmin):
    list_display = ["doc_id", "form", "fiscal_year", "status", "chunk_count", "index_version"]
    list_filter = ["status", "form"]
    search_fields = ["doc_id"]


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "total", "done", "failed", "created_at"]
    list_filter = ["status"]
