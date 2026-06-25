FROM python:3.12-slim

WORKDIR /app

COPY planner/requirements.txt requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY shared/ ./shared/
COPY planner/main.py main.py
COPY config.yaml config.yaml
COPY prompts.yaml prompts.yaml
COPY context.yaml context.yaml

ENV CONFIG_PATH=/app/config.yaml
ENV PROMPTS_PATH=/app/prompts.yaml
ENV CONTEXT_PATH=/app/context.yaml

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
