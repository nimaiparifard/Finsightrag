from rest_framework import serializers

from apps.chat.models import Conversation, Feedback, Message


class MessageSerializer(serializers.ModelSerializer):
    thumbs_up = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "role", "content", "citations", "chunks", "latency_s", "cost_usd", "cached", "refused",
                  "guardrails", "prompt_version", "created_at", "thumbs_up"]

    def get_thumbs_up(self, obj: Message) -> bool | None:
        fb = getattr(obj, "feedback", None)
        return fb.thumbs_up if fb else None


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "filters", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = [*ConversationSerializer.Meta.fields, "messages"]


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=3, max_length=2000)
    company = serializers.ListField(child=serializers.CharField(), required=False)
    year = serializers.ListField(child=serializers.CharField(), required=False)
    form = serializers.CharField(required=False)
    stream = serializers.BooleanField(default=False)

    def filters(self) -> dict:
        d = self.validated_data
        return {k: d[k] for k in ("company", "year", "form") if d.get(k)}


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ["thumbs_up", "comment"]
