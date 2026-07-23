"""Compatibility middleware for the retired onboarding paywall state.

Older bot instances could leave a user in ``onboarding_paywall``.  The product
now keeps the menu open after onboarding, so we clear that stale state and let
the requested action proceed.
"""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.states.photo import PhotoUploadStates


class PaywallGuardMiddleware(BaseMiddleware):
    """Migrate stale hard-paywall FSM state without blocking the menu."""

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")
        if state and await state.get_state() == PhotoUploadStates.onboarding_paywall.state:
            await state.clear()
        return await handler(event, data)
