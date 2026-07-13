from datetime import datetime, timezone
import time
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Chat, Message, User

from app.handlers.payment import _create_and_send_payment, handle_check_yookassa
from app.middlewares.paywall_guard import PaywallGuardMiddleware
from app.states.photo import PhotoUploadStates


def _message(text: str = "хочу оплатить") -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=42, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Test"),
        text=text,
    )


@pytest.mark.asyncio
async def test_any_message_restores_paywall_and_sends_payment():
    middleware = PaywallGuardMiddleware()
    handler = AsyncMock()
    state = AsyncMock()
    state.get_state.return_value = None
    state.get_data.return_value = {}
    analytics = AsyncMock()
    message = _message()
    user_data = {
        "user": {"onboarding_completed": True, "has_purchased": False},
    }

    with (
        patch("app.api.backend.backend.get_user", AsyncMock(return_value=user_data)) as get_user,
        patch("app.handlers.payment.start_onboarding_payment", new_callable=AsyncMock) as start_payment,
    ):
        await middleware(handler, message, {"state": state, "analytics": analytics})

    assert get_user.await_count == 1
    state.set_state.assert_awaited_with(PhotoUploadStates.onboarding_paywall)
    start_payment.assert_awaited_once_with(message, 42, state, analytics=analytics)
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_paywall_message_has_cooldown():
    middleware = PaywallGuardMiddleware()
    handler = AsyncMock()
    state = AsyncMock()
    state.get_state.return_value = PhotoUploadStates.onboarding_paywall.state
    state.get_data.return_value = {"_last_paywall_prompt_at": int(time.time())}
    message = _message()
    object.__setattr__(message, "answer", AsyncMock())

    with patch("app.handlers.payment.start_onboarding_payment", new_callable=AsyncMock) as start_payment:
        await middleware(handler, message, {"state": state})

    start_payment.assert_not_awaited()
    message.answer.assert_awaited_once_with(
        "Ссылка на оплату выше 👆\n"
        "После оплаты доступ откроется автоматически."
    )
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_purchased_user_is_not_intercepted():
    middleware = PaywallGuardMiddleware()
    handler = AsyncMock(return_value="handled")
    state = AsyncMock()
    state.get_state.return_value = None
    state.get_data.return_value = {}
    message = _message()

    with patch(
        "app.api.backend.backend.get_user",
        AsyncMock(return_value={"user": {"onboarding_completed": True, "has_purchased": True}}),
    ):
        result = await middleware(handler, message, {"state": state})

    assert result == "handled"
    handler.assert_awaited_once()
    state.set_state.assert_not_awaited()


class _FakeMessage:
    def __init__(self):
        self.answer = AsyncMock()


class _FakeCallback:
    def __init__(self):
        self.data = "check_yookassa_yk_1"
        self.from_user = User(id=42, is_bot=False, first_name="Test")
        self.message = _FakeMessage()
        self.answer = AsyncMock()


@pytest.mark.asyncio
async def test_payment_message_has_no_manual_check_button():
    message = _FakeMessage()

    with patch(
        "app.handlers.payment.backend.create_yookassa_payment",
        AsyncMock(return_value={
            "yookassa_id": "yk_1",
            "confirmation_url": "https://pay.example/1",
            "status": "pending",
            "reused": False,
        }),
    ):
        await _create_and_send_payment(message, 42, generations=20, rubles=289)

    kwargs = message.answer.await_args.kwargs
    button_texts = [
        button.text
        for row in kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "Оплатить 💳" in button_texts
    assert all("Проверить" not in text for text in button_texts)


@pytest.mark.asyncio
async def test_legacy_pending_check_does_not_send_chat_message():
    callback = _FakeCallback()
    state = AsyncMock()
    analytics = AsyncMock()

    with patch(
        "app.handlers.payment.backend.check_yookassa_payment",
        AsyncMock(return_value={
            "found": True,
            "yookassa_id": "yk_1",
            "status": "pending",
            "generations": 20,
            "amount_rubles": 289,
        }),
    ):
        await handle_check_yookassa(callback, state, analytics)

    callback.answer.assert_awaited_once_with(
        "Оплата пока не подтверждена. После оплаты доступ откроется автоматически.",
        show_alert=True,
    )
    callback.message.answer.assert_not_awaited()
