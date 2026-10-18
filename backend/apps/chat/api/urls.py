from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CompareView, ConversationViewSet, MessageFeedbackView

router = DefaultRouter()
router.register("conversations", ConversationViewSet, basename="conversation")
router.register("messages", MessageFeedbackView, basename="message")

urlpatterns = [path("compare/", CompareView.as_view(), name="compare"), *router.urls]
