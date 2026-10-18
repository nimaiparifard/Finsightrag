from django.conf import settings
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.documents import selectors, services

from .serializers import CompanySerializer, FilingSerializer, IngestionJobSerializer, IngestRequestSerializer


class CompanyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CompanySerializer
    queryset = selectors.companies()
    filterset_fields = ["ticker"]


class FilingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FilingSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        q = self.request.query_params
        return selectors.filings(q.get("ticker"), q.get("form"), q.get("status"))


class CanIngest(BasePermission):
    """Any signed-in user, unless INGEST_STAFF_ONLY is on: then staff or users with the admin role."""

    message = "Only staff can ingest filings on this deployment."

    def has_permission(self, request, view):  # type: ignore[no-untyped-def]
        u = request.user
        if not (u and u.is_authenticated):
            return False
        return (not settings.INGEST_STAFF_ONLY) or u.is_staff or getattr(u, "role", "") == "admin"


class IngestView(APIView):
    throttle_scope = "ingest"
    permission_classes = [CanIngest]

    @extend_schema(request=IngestRequestSerializer, responses={202: IngestionJobSerializer})
    def post(self, request):  # type: ignore[no-untyped-def]
        ser = IngestRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        job = services.create_ingestion_job(request.user, d["ticker"], (d["years"][0], d["years"][1]), d["forms"])
        job.refresh_from_db()
        return Response(IngestionJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class IngestionJobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IngestionJobSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return selectors.jobs_for(self.request.user)


class DocumentFileView(APIView):
    """Streams the source filing so the browser PDF viewer can render the cited page."""

    @extend_schema(responses={200: bytes})
    def get(self, request, doc_id):  # type: ignore[no-untyped-def]
        path = services.resolve_document_path(doc_id)
        ctype = "application/pdf" if path.suffix.lower() == ".pdf" else "text/html; charset=utf-8"
        resp = FileResponse(open(path, "rb"), content_type=ctype)
        resp["Content-Disposition"] = f'inline; filename="{path.name}"'
        resp["X-Content-Type-Options"] = "nosniff"
        if ctype.startswith("text/html"):  # filings are third-party HTML: never let them run script
            resp["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        return resp


class DocumentPageView(APIView):
    @extend_schema(responses={200: dict})
    def get(self, request, doc_id, page):  # type: ignore[no-untyped-def]
        return Response(services.read_page_text(doc_id, int(page)))
