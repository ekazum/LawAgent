# Stage 1: build the React frontend
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: backend + static frontend
FROM python:3.12-slim
WORKDIR /app

# OCR for scanned PDFs: tesseract (Hebrew + English) + poppler (pdf2image).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-heb poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/models

# CPU-only torch first — the default PyPI wheels bundle CUDA (~2.5GB extra)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image (HF_HOME) so containers start offline-ready
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"

COPY backend/ ./
COPY --from=frontend /build/dist ./static

# Drop root: run as an unprivileged user that can read /app (incl. the model cache)
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
