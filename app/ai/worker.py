"""
arq worker for processing AI tasks.

The worker:
1. Loads task details from DB
2. Routes to the correct provider via ProviderRouter
3. Handles submit -> poll -> download -> store lifecycle
4. Updates task status in DB at each step
5. Manages checkpoint/resume via checkpoint_data

Phase 0: Dispatcher skeleton. Provider-specific handlers added in later phases.
"""

import logging

from arq.connections import RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)


async def process_ai_task(ctx: dict, task_id: str) -> dict:
    """
    Main worker function. Dispatches to the appropriate handler based on task_type.

    Args:
        ctx: arq worker context
        task_id: UUID of the AITask to process

    Returns:
        dict with status and result info
    """
    logger.info("Processing task: %s", task_id)

    # TODO (Phase 2+): Load task from DB, route to handler, update status
    # Skeleton for now — each phase will add its handler

    return {"task_id": task_id, "status": "not_implemented"}


def _parse_redis_settings() -> RedisSettings:
    """Derive arq RedisSettings from the application REDIS_URL."""
    url = settings.REDIS_URL
    stripped = url.replace("redis://", "")
    host_port, _, database = stripped.partition("/")
    host, _, port_str = host_port.partition(":")
    port = int(port_str) if port_str else 6379
    db = int(database) if database else 0
    return RedisSettings(host=host, port=port, database=db)


class WorkerSettings:
    """arq worker settings."""
    functions = [process_ai_task]
    redis_settings = _parse_redis_settings()
    max_jobs = 10
    job_timeout = 600  # 10 minutes max per task
