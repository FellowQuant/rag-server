FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY scripts ./scripts
COPY llm.yaml.example ./llm.yaml.example

RUN uv sync --frozen
RUN chmod +x ./scripts/start.sh

EXPOSE 8001

CMD ["./scripts/start.sh"]
