"""Per-user generation lock to prevent concurrent generations."""

import logging

logger = logging.getLogger(__name__)

# Set of telegram_ids that currently have an active generation
_active_generations: set[int] = set()


def is_generating(telegram_id: int) -> bool:
    return telegram_id in _active_generations


def acquire(telegram_id: int) -> bool:
    """Try to acquire generation lock. Returns True if acquired, False if already active."""
    if telegram_id in _active_generations:
        logger.info(f"[tg={telegram_id}] Generation lock denied — already generating")
        return False
    _active_generations.add(telegram_id)
    logger.info(f"[tg={telegram_id}] Generation lock acquired")
    return True


def release(telegram_id: int) -> None:
    _active_generations.discard(telegram_id)
    logger.info(f"[tg={telegram_id}] Generation lock released")
