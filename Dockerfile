FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.5 \
    && useradd --create-home --uid 10001 appuser

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data
COPY --chown=appuser:appuser .streamlit ./.streamlit
COPY --chown=appuser:appuser streamlit_app.py ./streamlit_app.py

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)"]

CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
