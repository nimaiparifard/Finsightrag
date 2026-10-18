from rest_framework.routers import DefaultRouter

from .views import WatchlistViewSet

router = DefaultRouter()
router.register("collections", WatchlistViewSet, basename="collection")
urlpatterns = router.urls
