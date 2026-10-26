FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --upgrade pip \
    && pip install \
        "fastapi>=0.115.0" \
        "uvicorn>=0.32.0" \
        "pydantic>=2.0" \
        "pyarrow>=17.0" \
        "httpx>=0.27"

COPY app ./app
COPY pipeline ./pipeline
COPY data/restaurants.parquet data/catalog_meta.json ./data/

EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
