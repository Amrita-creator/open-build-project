FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY demo ./demo
COPY scripts ./scripts

RUN pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium \
    && python scripts/render_demo_screenshots.py \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /var/lib/inspo-mcp \
    && chown -R appuser:appuser /app /var/lib/inspo-mcp /ms-playwright

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

CMD ["sh", "-c", "uvicorn inspo_mcp.production:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"]
