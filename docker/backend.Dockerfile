# Development image for the UrbanPulse API.
#
# Deliberately excludes GeoPandas/LightGBM: the API reads precomputed geometry
# from PostGIS and never runs model training, so those belong to the offline
# pipeline image instead. Keeping them out cuts build time and image size
# substantially.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq is needed by psycopg (used by Alembic); curl is for container debugging.
RUN apt-get update \
 && apt-get install --no-install-recommends -y libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Copy the manifest first so dependency layers cache across source edits.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
