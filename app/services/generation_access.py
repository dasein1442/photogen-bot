"""Shared purchase gate for actions that consume generations.

The menu and catalogue remain available after onboarding.  This gate is used
only immediately before an action would ask the user to provide a source photo
or start a paid generation.
"""
import logging

from aiogram.types import Message

from app.api.backend import backend
from app.keyboards.payment import get_buy_keyboard
from app.services.analytics_sdk import AnalyticsClient

logger = logging.getLogger(__name__)


async def require_generations(
    message: Message,
    telegram_id: int,
    required: int,
    action: str,
    analytics: AnalyticsClient | None = None,
) -> bool:
    """Return whether the user can start an action costing ``required`` credits.

    A failed lookup never unlocks a paid action.  The backend remains the final
    authority and still validates the balance when a generation is created.
    """
    try:
        user_data = await backend.get_user(telegram_id=telegram_id)
        remaining = int(user_data.get("generations_remaining") or 0)
    except Exception as exc:
        logger.error("Could not load generation balance for %s: %s", telegram_id, exc)
        await message.answer("⚠️ Не удалось проверить баланс. Попробуй ещё раз.")
        return False

    if remaining >= required:
        return True

    if analytics:
        await analytics.track(
            "generation_access_required",
            user_id=str(telegram_id),
            properties={
                "action": action,
                "generations_remaining": remaining,
                "generations_required": required,
            },
        )

    generation_word = "генерация" if required == 1 else "генерации" if 2 <= required <= 4 else "генераций"
    await message.answer(
        f"Чтобы {action}, нужно {required} {generation_word}.\n\n"
        f"Сейчас на балансе: {remaining}. Выбери пакет — и сможешь сразу продолжить.",
        reply_markup=get_buy_keyboard(),
    )
    return False
