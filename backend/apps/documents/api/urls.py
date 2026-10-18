from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CompanyViewSet, DocumentFileView, DocumentPageView, FilingViewSet, IngestionJobViewSet, IngestView

router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("filings", FilingViewSet, basename="filing")
router.register("ingestion-jobs", IngestionJobViewSet, basename="ingestion-job")

urlpatterns = [
    path("filings/ingest/", IngestView.as_view(), name="filings-ingest"),
    path("documents/<str:doc_id>/file/", DocumentFileView.as_view(), name="document-file"),
    path("documents/<str:doc_id>/pages/<int:page>/", DocumentPageView.as_view(), name="document-page"),
    *router.urls,
]
