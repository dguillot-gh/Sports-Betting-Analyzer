# Stage 1: Build & Infrastructure
FROM python:3.11-slim as builder

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

# 2. Install Build dependencies for ONNX conversion
# Note: These are heavy but are discarded in Stage 2
# We pin numpy exactly to 1.26.4 to avoid breaking TensorFlow (which doesn't support NumPy 2.x yet)
RUN pip install --no-cache-dir "numpy==1.26.4" "tensorflow<2.16" "tf2onnx<1.16" "onnx<1.16" "ml_dtypes<0.4.0" xgboost

# 3. Download and Convert Models
COPY scripts/download_xgb_models.py scripts/convert_to_onnx.py ./scripts/
# We need the directory structure before running scripts
COPY scripts/nba_ml_reference ./scripts/nba_ml_reference
# Ensure directories exist
RUN mkdir -p scripts/nba_ml_reference/Models/XGBoost_Models scripts/nba_ml_reference/Models/NN_Models scripts/nba_ml_reference/Data

# Run model preparation (Downloads XGBoosst models and converts Keras to ONNX)
RUN echo "Starting model preparation..." && \
    python scripts/download_xgb_models.py && \
    python scripts/convert_to_onnx.py && \
    echo "Model preparation complete."

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

# Environment configuration
EXPOSE 8000
ENV PYTHONPATH=/app/src:/app/api:/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start application
CMD ["python", "-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
