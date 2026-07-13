"""Middleware that blocks all actions while user is in onboarding_paywall state."""
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.states.photo import PhotoUploadStates

logger = logging.getLogger(__name__)
PAYWALL_PROMPT_COOLDOWN_SECONDS = 300
PAYWALL_HINT_COOLDOWN_SECONDS = 30


class PaywallGuardMiddleware(BaseMiddleware):
    """Keep unpaid onboarding users inside a recoverable payment flow."""

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
        is_paywall = current_state == PhotoUploadStates.onboarding_paywall.state
        restored_user_info = None

        state_data = await state.get_data()
        if isinstance(state_data, dict) and state_data.get("_payment_access_granted"):
            return await handler(event, data)

        # FSM storage can be stale after onboarding. Backend purchase state is
        # authoritative: an unpaid user who finished onboarding must stay in
        # the payment flow regardless of the current FSM state.
        if not is_paywall and isinstance(event, Message):
            try:
                from app.api.backend import backend

                user_data = await backend.get_user(telegram_id=event.from_user.id)
                user_info = user_data.get("user", {})
                restored_user_info = user_info
                if user_info.get("has_purchased"):
                    await state.update_data(_payment_access_granted=True)
                is_paywall = bool(
                    user_info.get("onboarding_completed")
                    and not user_info.get("has_purchased")
                )
                if is_paywall:
                    await state.set_state(PhotoUploadStates.onboarding_paywall)
            except Exception as e:
                logger.warning(f"PaywallGuard: не удалось восстановить paywall: {e}")

        if not is_paywall:
            return await handler(event, data)

        # State is onboarding_paywall — but check if user already purchased (e.g. manually granted)
        try:
            from app.api.backend import backend
            telegram_id = event.from_user.id if event.from_user else None
            if telegram_id:
                user_info = restored_user_info
                if user_info is None:
                    user_data = await backend.get_user(telegram_id=telegram_id)
                    user_info = user_data.get("user", {})
                if user_info.get("has_purchased"):
                    await state.clear()
                    await state.update_data(_payment_access_granted=True)
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
                or event.data.startswith("retry_payment_")
                or event.data == "onboarding_pay"
                or event.data == "payment_open_menu"
            ):
                return await handler(event, data)

        # Any message from an unpaid onboarding user brings back the payment
        # flow. Cooldown prevents chat spam when the user sends several
        # messages in a row; backend reuse prevents duplicate YooKassa payments.
        if isinstance(event, Message):
            now = int(time.time())
            last_prompt_at = int(state_data.get("_last_paywall_prompt_at") or 0)
            if now - last_prompt_at < PAYWALL_PROMPT_COOLDOWN_SECONDS:
                last_hint_at = int(state_data.get("_last_paywall_hint_at") or 0)
                if now - last_hint_at >= PAYWALL_HINT_COOLDOWN_SECONDS:
                    await state.update_data(_last_paywall_hint_at=now)
                    await event.answer(
                        "Ссылка на оплату выше 👆\n"
                        "После оплаты доступ откроется автоматически."
                    )
                return
            await state.update_data(_last_paywall_prompt_at=now)

            from app.handlers.payment import start_onboarding_payment

            await start_onboarding_payment(
                event,
                event.from_user.id,
                state,
                analytics=data.get("analytics"),
            )
            return

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
