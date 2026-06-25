FROM python:3.12-slim

WORKDIR /app

# Install deps (cached layer — only rebuilds when requirements change)
COPY planner/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared library and agent source
COPY shared/ ./shared/
COPY planner/main.py main.py
COPY config.yaml config.yaml

ENV CONFIG_PATH=/app/config.yaml
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
