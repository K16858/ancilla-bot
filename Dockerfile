FROM node:22-slim AS webui
WORKDIR /webui
COPY webui/package.json webui/package-lock.json ./
RUN npm ci
COPY webui ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY ancilla_bot ./ancilla_bot
COPY data/prompts ./data/prompts
COPY skills ./skills
COPY --from=webui /webui/dist ./webui/dist

RUN pip install --no-cache-dir .

RUN mkdir -p /app/workspace /app/data

EXPOSE 8765 8766 8767

CMD ["ancilla", "run", "--no-repl"]
