from rest_framework import viewsets

from apps.collections.models import Watchlist

from .serializers import WatchlistSerializer


class WatchlistViewSet(viewsets.ModelViewSet):
    serializer_class = WatchlistSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return Watchlist.objects.filter(owner=self.request.user).prefetch_related("companies")

    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        serializer.save(owner=self.request.user)
