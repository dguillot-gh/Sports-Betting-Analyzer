# Deployment Guide

## Prerequisites

- Docker & Docker Compose installed on server
- GitHub account with repos pushed
- (Optional) Kaggle API key for data downloads
- (Optional) Odds API and BallDontLie API keys

---

## Quick Start (Local)

```bash
# Clone both repos to same parent directory
git clone https://github.com/YOUR_USERNAME/SportsBettingAnalyzer.git
git clone https://github.com/YOUR_USERNAME/PythonMLService.git

# Create environment file
cd SportsBettingAnalyzer
cp .env.example .env
# Edit .env with your API keys

# Build and run
docker-compose up -d

# Visit http://localhost
```

---

## Production Deployment (Linux Server)

### 1. Initial Setup

```bash
# SSH to your server
ssh user@your-server

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Create project directory
mkdir -p ~/sports-betting
cd ~/sports-betting

# Clone repos
git clone https://github.com/YOUR_USERNAME/SportsBettingAnalyzer.git
git clone https://github.com/YOUR_USERNAME/PythonMLService.git

cd SportsBettingAnalyzer
```

### 2. Configure Environment

```bash
# Create .env file
cp .env.example .env
nano .env  # Add your API keys
```

### 3. Run with Docker Compose

```bash
# Start services
docker-compose up -d

# Optional: Enable Watchtower for auto-updates
docker-compose --profile production up -d

# Check status
docker-compose ps
docker-compose logs -f
```

---

## GitHub Actions Auto-Deploy

When you push to `main`, GitHub Actions will:
1. Build new Docker images
2. Push to GitHub Container Registry (ghcr.io)
3. Watchtower (if enabled) will auto-pull and restart

### Pull Latest Images Manually

```bash
docker-compose pull
docker-compose up -d
```

---

## Ports

| Service | Port |
|---------|------|
| Frontend | 80 |
| Backend API | 8000 |

---

## Health Checks

```bash
# Backend
curl http://localhost:8000/health

# Frontend
curl http://localhost/health
```

---

## Troubleshooting

### View Logs
```bash
docker-compose logs backend
docker-compose logs frontend
```

### Restart Services
```bash
docker-compose restart
```

### Rebuild After Code Changes
```bash
docker-compose build --no-cache
docker-compose up -d
```

### Reset Everything
```bash
docker-compose down -v
docker-compose up -d --build
```
