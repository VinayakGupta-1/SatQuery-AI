# SatQuery AI analysis service.
#
#   docker build -t satquery-backend backend
#   docker run -p 8000:8000 --env-file backend/.env satquery-backend
#
# rasterio's wheels bundle GDAL, so no system GDAL is needed.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SATQUERY_STORAGE_ROOT=/data

WORKDIR /app

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY app ./app
COPY scripts ./scripts

# Run unprivileged; uploads, fetched scenes and outputs live in /data.
RUN useradd --create-home --uid 10001 satquery \
    && mkdir -p /data && chown satquery:satquery /data
USER satquery
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
