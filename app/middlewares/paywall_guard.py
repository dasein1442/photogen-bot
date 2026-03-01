"""Middleware that blocks all actions while user is in onboarding_paywall state."""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, LabeledPrice
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.states.photo import PhotoUploadStates

logger = logging.getLogger(__name__)


class PaywallGuardMiddleware(BaseMiddleware):
    """Block all user actions except payment while in onboarding_paywall state."""

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext = data.get("state")
        if not state:
            return await handler(event, data)

        current_state = await state.get_state()
        if current_state != PhotoUploadStates.onboarding_paywall.state:
            return await handler(event, data)

        # Allow pre_checkout and successful_payment through
        if isinstance(event, Message):
            if event.successful_payment:
                return await handler(event, data)
            # Allow /start commands through (they have their own guard)
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

        # Allow buy_generations callback
        if isinstance(event, CallbackQuery):
            if event.data in ("buy_generations",):
                return await handler(event, data)

        # Block everything else — show price + invoice
        telegram_id = event.from_user.id

        try:
            price_data = await backend.get_price(telegram_id, context="onboarding_paywall")
            tier = price_data["tiers"][0]
            stars = tier["stars"]
            generations = tier["generations"]
        except Exception:
            stars = 299
            generations = 20

        if isinstance(event, Message):
            target = event
        else:
            target = event.message
            await event.answer()

        await target.answer(
            f"Открой доступ к 70+ стилям — {generations} генераций всего за {stars} ⭐️\n\n"
            "Деловая съёмка, пляж, Pinterest, Vogue и многое другое 👇"
        )

        await target.bot.send_invoice(
            chat_id=target.chat.id,
            title=f"{generations} генераций",
            description=f"Покупка {generations} генераций для создания AI-фото",
            payload=f"buy_{generations}_{telegram_id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{generations} генераций", amount=stars)],
        )

        return  # do NOT call the handler
