# Image des collecteurs UrbanHub (streaming vélos, IoT pollution, batch NOAA)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
WORKDIR /app

# Dépendances d'ingestion uniquement (pas de Jupyter / matplotlib dans les conteneurs)
RUN pip install --no-cache-dir pandas numpy pyarrow requests boto3 SQLAlchemy psycopg2-binary python-dotenv

COPY urbanhub ./urbanhub
COPY sql ./sql

ENTRYPOINT ["python", "-m", "urbanhub"]
CMD ["--help"]
