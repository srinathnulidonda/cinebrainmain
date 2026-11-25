# Dockerfile

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" PORT=8000
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
