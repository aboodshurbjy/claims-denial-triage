FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY sql ./sql
COPY rules ./rules
COPY docker/entrypoint.sh ./docker/entrypoint.sh

ENV TRIAGE_DATA_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000

ENTRYPOINT ["sh", "./docker/entrypoint.sh"]
