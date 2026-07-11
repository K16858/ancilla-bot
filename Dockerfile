FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY ancilla_bot ./ancilla_bot
COPY data/prompts ./data/prompts

RUN pip install --no-cache-dir .

RUN mkdir -p /app/workspace /app/data

EXPOSE 8765 8766

CMD ["ancilla", "run", "--no-repl"]
