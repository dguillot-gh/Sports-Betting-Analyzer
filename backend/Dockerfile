# Stage 1: Build & Infrastructure
FROM python:3.11-slim as builder

WORKDIR /app

# Install system build dependencies (compilers + R development headers)
RUN apt-get update && apt-get install -y \
    curl \
    r-base \
    r-base-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. Install R dependencies (Slowest layer - cached first)
RUN R -e "install.packages(c('jsonlite', 'dplyr'), repos='https://cloud.r-project.org')" && \
    R -e "install.packages(c('nflseedR', 'nflreadr'), repos='https://cloud.r-project.org')" && \
    R -e "install.packages('baseballr', repos='https://cloud.r-project.org')"

# 2. Install Heavy ML dependencies (Disabled for faster builds - using fallback logic)
# RUN pip install --no-cache-dir --default-timeout=1000 torch --index-url https://download.pytorch.org/whl/cpu
# RUN pip install --no-cache-dir --default-timeout=1000 tensorflow
RUN pip install --no-cache-dir --default-timeout=1000 xgboost

# 3. Install other Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# Stage 2: Final Runtime Environment
FROM python:3.11-slim

WORKDIR /app

# Install ONLY runtime dependencies (minimal R and system libs)
RUN apt-get update && apt-get install -y \
    curl \
    r-base \
    libcurl4 \
    libxml2 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy R libraries from builder
COPY --from=builder /usr/local/lib/R/site-library /usr/local/lib/R/site-library

# Copy application source code
# By copying this AFTER dependencies, we ensure small code changes are nearly instant
COPY . .

# Create necessary data directories
RUN mkdir -p data/nascar data/nba data/nfl models

# Download XGBoost model files
# Uses Python script to fetch models; runs only when copy layer changes
RUN python scripts/download_xgb_models.py

# Environment configuration
EXPOSE 8000
ENV PYTHONPATH=/app/src:/app/api:/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start application
CMD ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
