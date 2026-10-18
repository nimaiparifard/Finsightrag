from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat import selectors, services
from apps.chat.clients import ServingClient

from .serializers import (
    AskSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    FeedbackSerializer,
    MessageSerializer,
)


class ConversationViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          mixins.DestroyModelMixin, viewsets.GenericViewSet):
    @property
    def throttle_scope(self) -> str | None:
        """Only the LLM-backed action is rate limited (ScopedRateThrottle ignores a None scope)."""
        return "llm" if getattr(self, "action", None) == "messages" else None

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return selectors.conversations_for(self.request.user).prefetch_related("messages__feedback")

    def get_serializer_class(self):  # type: ignore[no-untyped-def]
        return ConversationDetailSerializer if self.action == "retrieve" else ConversationSerializer

    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        serializer.save(user=self.request.user)

    @extend_schema(request=AskSerializer, responses=MessageSerializer)
    @action(detail=True, methods=["post"], url_path="messages")
    def messages(self, request, pk=None):  # type: ignore[no-untyped-def]
        """Ask a question. `stream: true` returns Server-Sent Events (retrieval, token*, final, saved)."""
        conv = self.get_object()
        ser = AskSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        q, f = ser.validated_data["question"], ser.filters()
        if ser.validated_data["stream"]:
            resp = StreamingHttpResponse(services.ask_stream(conv, q, f), content_type="text/event-stream")
            resp["Cache-Control"] = "no-cache"
            resp["X-Accel-Buffering"] = "no"
            return resp
        return Response(MessageSerializer(services.ask(conv, q, f)).data, status=status.HTTP_201_CREATED)


class MessageFeedbackView(viewsets.GenericViewSet):
    serializer_class = FeedbackSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return selectors.messages_for(self.request.user)

    @extend_schema(request=FeedbackSerializer, responses=FeedbackSerializer)
    @action(detail=True, methods=["post"], url_path="feedback")
    def feedback(self, request, pk=None):  # type: ignore[no-untyped-def]
        message = get_object_or_404(self.get_queryset(), pk=pk)
        ser = FeedbackSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        fb = services.give_feedback(message, **ser.validated_data)
        return Response(FeedbackSerializer(fb).data)



class CompareView(APIView):
    """Stateless agentic comparison: decompose -> answer each part -> cited synthesis."""

    throttle_scope = "llm"

    @extend_schema(request=AskSerializer, responses={200: dict})
    def post(self, request):  # type: ignore[no-untyped-def]
        ser = AskSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(ServingClient().compare(ser.validated_data["question"], ser.filters()))
