from rest_framework import serializers

from apps.collections.models import Watchlist
from apps.documents.models import Company


class WatchlistSerializer(serializers.ModelSerializer):
    tickers = serializers.SlugRelatedField(source="companies", many=True, slug_field="ticker",
                                           queryset=Company.objects.all())
    company_names = serializers.SerializerMethodField()

    class Meta:
        model = Watchlist
        fields = ["id", "name", "tickers", "company_names", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_company_names(self, obj: Watchlist) -> list[str]:
        return [c.name for c in obj.companies.all()]

    def validate_name(self, value: str) -> str:
        qs = Watchlist.objects.filter(owner=self.context["request"].user, name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("You already have a watchlist with this name.")
        return value
