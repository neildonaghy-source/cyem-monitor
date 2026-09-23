FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata curl libexpat1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY static ./static
COPY data ./data
RUN mkdir -p /data && useradd -u 1000 -m cyem && chown -R cyem:cyem /app /data
USER cyem
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--log-level", "info"]
