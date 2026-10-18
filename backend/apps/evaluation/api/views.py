from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.evaluation.models import EvalRun
from apps.evaluation.services import import_runs


class EvalRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvalRun
        fields = ["id", "config_name", "dataset", "n_questions", "metrics", "git_sha", "created_at"]


class EvalRunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EvalRunSerializer
    queryset = EvalRun.objects.all()
    filterset_fields = ["config_name", "dataset"]

    @action(detail=False, methods=["post"], permission_classes=[IsAdminUser])
    def refresh(self, request):  # type: ignore[no-untyped-def]
        """Import any new result files from the ml output directory."""
        return Response({"imported": import_runs()})
