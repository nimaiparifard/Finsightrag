# Build context is the REPO ROOT (the image also installs the ml package):
#   docker build -f backend/Dockerfile .
# Same image runs the web app, the Celery worker and beat (command differs in compose).
FROM python:3.15-slim AS builder
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY backend/requirements.txt backend-requirements.txt
RUN pip install -r backend-requirements.txt
# CPU torch by default (pass --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 for GPU workers)
RUN pip install torch --index-url ${TORCH_INDEX}
COPY ml ./ml
RUN pip install ./ml

FROM python:3.15-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod HF_HOME=/app/data/hf-cache
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app/backend
COPY --chown=app backend/ /app/backend/
COPY --chown=app ml/configs /app/ml/configs
# the app user must own the working dir (sqlite fallback, staticfiles); collectstatic builds the whitenoise manifest
RUN chown app:app /app/backend && DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput >/dev/null     && chown -R app:app /app/backend/staticfiles
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/health/')"
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "180", "--worker-class", "gthread", "--threads", "4"]
