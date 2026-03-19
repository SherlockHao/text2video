# text2video

AIGC video editing tool server-side service.

## Tech Stack

- **Runtime**: Python 3.11 + FastAPI
- **Database**: PostgreSQL 15 + SQLAlchemy 2.0 + Alembic
- **Queue**: Redis 7 + arq
- **Container**: Docker + docker-compose

## Quick Start

```bash
# 1. Clone
git clone git@github.com:SherlockHao/text2video.git
cd text2video

# 2. Create environment config
cp .env.example .env

# 3. Start all services
docker compose up -d --build

# 4. Verify
curl http://localhost:8000/api/v1/health
# => {"status": "ok", "version": "0.1.0"}
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| app     | 8000 | FastAPI server |
| worker  | -    | arq async task worker |
| db      | 5432 | PostgreSQL |
| redis   | 6379 | Redis |

## Development

```bash
# Run database migrations
make migrate

# Create a new migration
make migration msg="add new table"

# Run tests
make test

# Lint & format
make lint
make format

# View logs
docker compose logs -f app
```

## API Docs

After starting the service, visit: http://localhost:8000/docs
