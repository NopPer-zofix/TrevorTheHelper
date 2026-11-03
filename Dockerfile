FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
RUN pip install .

RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data
USER app

# Overridden per service in docker-compose.yml
CMD ["aggregator-bot"]
