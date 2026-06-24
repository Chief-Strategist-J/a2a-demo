FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (Docker layer caching – rebuilt only when
# requirements.txt changes, not on every code change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY . .

# Expose the Worker's A2A port
EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
