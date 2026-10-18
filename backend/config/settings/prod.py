from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
INGEST_STAFF_ONLY = env.bool("INGEST_STAFF_ONLY", default=True)
SECRET_KEY = env("DJANGO_SECRET_KEY")  # required: no insecure default in prod
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)  # TLS is terminated by the proxy
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = env.bool("SECURE_COOKIES", default=False)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
