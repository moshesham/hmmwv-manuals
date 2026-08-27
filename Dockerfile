FROM python:3.11-slim

# Build-time dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY ingestion/ ingestion/
COPY vector_index/ vector_index/
COPY schemas/ schemas/

ENV PYTHONPATH=/app
CMD ["python", "-m", "ingestion.run_ingestion", "--help"]
