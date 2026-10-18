from django.db.models import QuerySet

from .models import Conversation, Message


def conversations_for(user) -> QuerySet[Conversation]:  # type: ignore[no-untyped-def]
    return Conversation.objects.filter(user=user)


def messages_for(user) -> QuerySet[Message]:  # type: ignore[no-untyped-def]
    return Message.objects.filter(conversation__user=user)
