"""Middleware that blocks all actions while user is in onboarding_paywall state."""
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

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

        # State is onboarding_paywall — but check if user already purchased (e.g. manually granted)
        try:
            from app.api.backend import backend
            telegram_id = event.from_user.id if event.from_user else None
            if telegram_id:
                user_data = await backend.get_user(telegram_id=telegram_id)
                if user_data.get("user", {}).get("has_purchased"):
                    await state.clear()
                    return await handler(event, data)
        except Exception as e:
            logger.warning(f"PaywallGuard: не удалось проверить has_purchased: {e}")

        # Allow successful_payment through (legacy safety)
        if isinstance(event, Message):
            if event.successful_payment:
                return await handler(event, data)
            # Allow /start and /menu commands through (they have their own guard)
            if event.text and (event.text.startswith("/start") or event.text.startswith("/menu")):
                return await handler(event, data)

        # Allow payment-related callbacks through
        if isinstance(event, CallbackQuery):
            if event.data and (
                event.data == "buy_generations"
                or event.data.startswith("buy_tier_")
                or event.data.startswith("check_yookassa_")
                or event.data == "onboarding_pay"
            ):
                return await handler(event, data)

        # Block everything else — show buy button
        if isinstance(event, Message):
            target = event
        else:
            target = event.message
            await event.answer()

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Перейти к оплате 💳", callback_data="onboarding_pay")],
        ])

        await target.answer(
            "Открой доступ к 70+ стилям!\n\n"
            "Деловая съёмка, пляж, Pinterest, Vogue и многое другое.",
            reply_markup=keyboard,
        )

        return  # do NOT call the handler
