import pytest
from rest_framework.test import APIClient

from apps.users.models import User


@pytest.fixture
def user(db):
    return User.objects.create_user("analyst@example.com", "s3cret-pass!")


@pytest.fixture
def other_user(db):
    return User.objects.create_user("other@example.com", "s3cret-pass!")


@pytest.fixture
def api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture
def anon():
    return APIClient()
