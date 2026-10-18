from django.db import connection
from django.http import JsonResponse
from django.urls import path


def health(_request):  # type: ignore[no-untyped-def]
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


urlpatterns = [path("health/", health, name="health")]
