from rest_framework import serializers

from apps.documents.models import Company, Filing, IngestionJob


class CompanySerializer(serializers.ModelSerializer):
    filing_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Company
        fields = ["id", "ticker", "name", "cik", "filing_count"]


class FilingSerializer(serializers.ModelSerializer):
    ticker = serializers.CharField(source="company.ticker", read_only=True)

    class Meta:
        model = Filing
        fields = ["id", "ticker", "doc_id", "form", "fiscal_year", "period_end", "status", "chunk_count",
                  "index_version", "source_url", "error"]


class IngestRequestSerializer(serializers.Serializer):
    ticker = serializers.CharField(max_length=12)
    years = serializers.ListField(child=serializers.IntegerField(min_value=1993, max_value=2100),
                                  min_length=2, max_length=2, help_text="[first_fiscal_year, last_fiscal_year]")
    forms = serializers.ListField(child=serializers.ChoiceField(choices=["10-K", "10-Q"]), min_length=1,
                                  default=["10-K"])


class IngestionJobSerializer(serializers.ModelSerializer):
    progress = serializers.IntegerField(read_only=True)

    class Meta:
        model = IngestionJob
        fields = ["id", "status", "params", "total", "done", "failed", "progress", "error", "created_at"]
