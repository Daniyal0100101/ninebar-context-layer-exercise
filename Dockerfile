FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . /app/

# Set Python path
ENV PYTHONPATH=/app/src

# Create outputs directory
RUN mkdir -p outputs

# Default command
CMD ["python", "-m", "context_layer.demo"]