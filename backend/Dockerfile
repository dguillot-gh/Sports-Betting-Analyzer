# Python ML Service Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including R
RUN apt-get update && apt-get install -y \
    curl \
    r-base \
    r-base-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    && rm -rf /var/lib/apt/lists/*

# Install R packages for NFL simulations
RUN R -e "install.packages(c('jsonlite', 'dplyr'), repos='https://cloud.r-project.org')" && \
    R -e "install.packages('nflseedR', repos='https://cloud.r-project.org')"

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create data directories
RUN mkdir -p data/nascar data/nba data/nfl models

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONPATH=/app/src:/app/api:/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the API
CMD ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
