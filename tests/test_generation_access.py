from unittest.mock import AsyncMock, patch

import pytest

from app.services.generation_access import require_generations


@pytest.mark.asyncio
async def test_require_generations_allows_user_with_enough_balance():
    message = AsyncMock()
    analytics = AsyncMock()

    with patch(
        "app.services.generation_access.backend.get_user",
        AsyncMock(return_value={"generations_remaining": 2}),
    ):
        allowed = await require_generations(
            message, telegram_id=10, required=2, action="улучшить фото", analytics=analytics
        )

    assert allowed is True
    message.answer.assert_not_awaited()
    analytics.track.assert_not_awaited()


@pytest.mark.asyncio
async def test_require_generations_shows_purchase_gate_before_paid_action():
    message = AsyncMock()
    analytics = AsyncMock()

    with patch(
        "app.services.generation_access.backend.get_user",
        AsyncMock(return_value={"generations_remaining": 0}),
    ):
        allowed = await require_generations(
            message, telegram_id=10, required=2, action="улучшить фото", analytics=analytics
        )

    assert allowed is False
    assert "Сейчас на балансе: 0" in message.answer.await_args.args[0]
    analytics.track.assert_awaited_once()
