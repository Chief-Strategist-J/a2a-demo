FROM python:3.12-slim

WORKDIR /app

COPY worker/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY worker/main.py main.py
COPY config.yaml config.yaml
COPY prompts.yaml prompts.yaml
COPY context.yaml context.yaml

ENV CONFIG_PATH=/app/config.yaml
ENV PROMPTS_PATH=/app/prompts.yaml
ENV CONTEXT_PATH=/app/context.yaml

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
