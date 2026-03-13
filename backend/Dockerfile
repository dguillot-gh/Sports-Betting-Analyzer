# Stage 1: Build & Infrastructure
FROM python:3.11-slim as builder

# Build arguments for versioning
ARG VERSION=unknown
ARG GIT_SHA=unknown
ARG GIT_BRANCH=unknown

WORKDIR /app

# Install system build dependencies (compilers + R development headers)
RUN apt-get update && apt-get install -y \
    curl \
    git \
    r-base \
    r-base-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 1. Install R dependencies (Using Posit Binary Repo to skip compilation)
# Force arrow to use precompiled binaries and skip long C++ compilation
ENV LIBARROW_BINARY=true
ENV NOT_CRAN=true
RUN R -e "options(repos = c(CRAN = 'https://packagemanager.posit.co/cran/__linux__/bookworm/latest')); install.packages(c('jsonlite', 'dplyr', 'nflseedR', 'nflreadr', 'baseballr', 'hoopR', 'arrow'))"

# 2. Install Build dependencies
# We now only need basic build tools since we removed heavy NN dependencies
RUN pip install --no-cache-dir xgboost

# 3. Download Models (XGBoosst models)
COPY scripts/download_xgb_models.py ./scripts/
# Copy the entire nba_ml_reference directory
COPY scripts/nba_ml_reference ./scripts/nba_ml_reference
RUN mkdir -p scripts/nba_ml_reference/Models/XGBoost_Models scripts/nba_ml_reference/Models/NN_Models scripts/nba_ml_reference/Data
RUN python scripts/download_xgb_models.py

# 4. Install other Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
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
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy R libraries from builder
COPY --from=builder /usr/local/lib/R/site-library /usr/local/lib/R/site-library

# Copy application source code
COPY . .

# Copy the models and data that were downloaded/converted in the builder stage
COPY --from=builder /app/scripts/nba_ml_reference /app/scripts/nba_ml_reference

# Create necessary data directories
RUN mkdir -p data/nascar data/nba data/nfl data/ncaab data/baseball models

# Removed ONNX conversion step as we are sticking with XGBoost

# Environment configuration
EXPOSE 8000
ENV PYTHONPATH=/app/src:/app/api:/app
ENV PYTHONUNBUFFERED=1

# Version information
ARG VERSION=unknown
ARG GIT_SHA=unknown
ARG GIT_BRANCH=unknown
ENV APP_VERSION=$VERSION
ENV GIT_SHA=$GIT_SHA
ENV GIT_BRANCH=$GIT_BRANCH

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start application
CMD ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
