# Build context is the REPO ROOT:  docker build -f serving/Dockerfile .
FROM python:3.12-slim AS builder
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY serving/requirements.txt serving-requirements.txt
RUN pip install -r serving-requirements.txt
RUN pip install torch --index-url ${TORCH_INDEX}
COPY ml ./ml
RUN pip install ./ml

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" HF_HOME=/app/data/hf-cache \
    FINSIGHT_CONFIG=/app/ml/configs/dense_rerank_ctx.yaml
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app serving/app /app/serving/app
COPY --chown=app ml/configs /app/ml/configs
USER app
WORKDIR /app/serving
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8001/health')"
# --factory: the index is loaded at startup, not at import time
CMD ["uvicorn", "app.main:get_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
