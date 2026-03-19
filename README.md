# text2video

AIGC video editing tool — automatically generates short videos from text scripts. The pipeline breaks down a script into shots, generates images, creates video clips, synthesizes narration via TTS, and assembles the final video with aligned audio.

## Tech Stack

- **Runtime**: Python 3.11 + FastAPI + Uvicorn
- **Database**: PostgreSQL 15 + SQLAlchemy 2.0 (async) + Alembic migrations
- **Task Queue**: Redis 7 + arq (async background workers)
- **AI Providers**: Qwen (LLM), Jimeng (image gen), Seedance2 / Kling (video gen), MiniMax / ElevenLabs (TTS)
- **Assembly**: FFmpeg (audio-video alignment + concatenation)
- **Container**: Docker + docker-compose

## Quick Start

```bash
# 1. Clone
git clone git@github.com:SherlockHao/text2video.git
cd text2video

# 2. Create environment config
cp .env.example .env
# Edit .env with your API keys

# 3. Start all services
docker compose up -d --build

# 4. Run database migrations
make migrate-docker

# 5. Verify
curl http://localhost:8000/api/v1/health
# => {"status": "ok", "version": "0.1.0"}
```

## API Documentation

After starting the service, visit: http://localhost:8000/docs

## Project Structure

```
app/
  api/v1/         # REST endpoints (projects, scripts, shots, tts, videos, assembly, health)
  ai/             # AI provider integrations and worker
    providers/    # Qwen, Jimeng, Seedance2, Kling, ElevenLabs, MiniMax TTS
    prompts/      # Prompt templates
  core/           # Config, logging, exceptions
  models/         # SQLAlchemy ORM models
  repositories/   # Data access layer
  services/       # Business logic (pipeline, FFmpeg utils, etc.)
vendor/           # Third-party SDK wrappers (Qwen, Jimeng)
data/             # Static data files (sensitive_words.txt)
alembic/          # Database migration scripts
tests/            # Pytest test suite
```

## Architecture

1. **Script Breakdown** — LLM (Qwen) splits a text script into a storyboard of numbered shots with scene descriptions, narration, and image prompts.
2. **Image Generation** — Jimeng generates a reference image for each shot.
3. **Video Generation** — Seedance2 or Kling converts each image into a short video clip (image-to-video).
4. **TTS Generation** — MiniMax or ElevenLabs synthesizes narration audio for each shot.
5. **Assembly** — FFmpeg aligns each video clip to its audio track, then concatenates all clips into the final MP4 with a downloadable asset package.

## Services

| Service | Port | Description |
|---------|------|-------------|
| app     | 8000 | FastAPI server |
| worker  | -    | arq async task worker |
| db      | 5432 | PostgreSQL |
| redis   | 6379 | Redis |

## Development

```bash
# Install locally (with dev deps)
make install

# Run dev server with hot reload
make dev

# Run background worker
make worker

# Database migrations
make migrate                      # apply migrations (local)
make migrate-docker               # apply migrations (docker)
make migration msg="add table"    # create new migration

# Testing
make test

# Linting & formatting
make lint
make format

# Docker
make docker-up          # build & start all services
make docker-down        # stop services
make docker-build       # rebuild images
make docker-logs        # tail all logs
make docker-logs-worker # tail worker logs
make docker-restart     # restart services
make docker-clean       # stop & remove volumes

# Status check
make status             # show containers + health endpoints
```

## Testing

```bash
make test
```

Runs the full pytest suite covering API endpoints, services, providers, and utilities.
