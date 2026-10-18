from django.conf import settings
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied

from .serializers import RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def create(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not settings.ALLOW_REGISTRATION:
            raise PermissionDenied("Registration is closed. Ask an administrator for an account.")
        return super().create(request, *args, **kwargs)


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):  # type: ignore[no-untyped-def]
        return self.request.user
