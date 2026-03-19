# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir hatchling

COPY pyproject.toml .
COPY app/ app/
COPY vendor/ vendor/
COPY data/ data/
RUN pip install --no-cache-dir .

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

# Install FFmpeg for audio-video assembly
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . .
COPY alembic.ini .
COPY alembic/ alembic/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
