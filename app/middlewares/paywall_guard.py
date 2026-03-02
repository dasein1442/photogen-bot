"""Middleware that blocks all actions while user is in onboarding_paywall state."""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.keyboards.payment import get_payment_method_keyboard
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

        # Allow payment-related callbacks through
        if isinstance(event, CallbackQuery):
            if event.data and (
                event.data == "buy_generations"
                or event.data.startswith("pm_stars_")
                or event.data.startswith("pm_sbp_")
                or event.data.startswith("buy_tier_")
            ):
                return await handler(event, data)

        # Block everything else — show payment method selection
        if isinstance(event, Message):
            target = event
        else:
            target = event.message
            await event.answer()

        await target.answer(
            "Открой доступ к 70+ стилям!\n\n"
            "Деловая съёмка, пляж, Pinterest, Vogue и многое другое.\n\n"
            "Выбери способ оплаты 👇",
            reply_markup=get_payment_method_keyboard("onboarding"),
        )

        return  # do NOT call the handler
