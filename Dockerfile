FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium && playwright install-deps chromium

COPY . .

RUN cd frontend && npm install && npm run build

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -m backend.core.health --url http://127.0.0.1:8000/health --timeout 5

CMD ["python", "-m", "uvicorn", "backend.core.server:app", "--host", "0.0.0.0", "--port", "8000"]
