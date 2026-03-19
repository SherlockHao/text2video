import asyncio
import logging

from arq.connections import RedisSettings

from app.core.config import settings
from app.ai.providers import get_provider

logger = logging.getLogger(__name__)


async def process_ai_task(ctx: dict, task_id: str) -> None:
    """Process an AI generation task dispatched via arq.

    Args:
        ctx: arq worker context.
        task_id: Unique identifier for the task to process.
    """
    logger.info("Starting AI task: %s", task_id)

    # TODO: look up task details from DB to determine provider type
    # For now, default to text_to_video as a placeholder
    task_type = "text_to_video"

    try:
        provider = get_provider(task_type)
        logger.info("Using provider '%s' for task %s", provider.provider_name, task_id)
        await asyncio.sleep(1)  # placeholder for actual work
        logger.info("AI task %s completed successfully", task_id)
    except Exception:
        logger.exception("AI task %s failed", task_id)
        raise


def _parse_redis_settings() -> RedisSettings:
    """Derive arq RedisSettings from the application REDIS_URL."""
    url = settings.REDIS_URL  # e.g. redis://redis:6379/0
    # Strip scheme
    stripped = url.replace("redis://", "")
    host_port, _, database = stripped.partition("/")
    host, _, port_str = host_port.partition(":")
    port = int(port_str) if port_str else 6379
    db = int(database) if database else 0
    return RedisSettings(host=host, port=port, database=db)


class WorkerSettings:
    """arq worker settings — referenced by ``arq worker app.ai.worker.WorkerSettings``."""

    functions = [process_ai_task]
    redis_settings = _parse_redis_settings()
