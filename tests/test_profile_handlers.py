from unittest.mock import AsyncMock, call

import pytest

from app.handlers.profile import handle_set_new_photo, handle_set_partner_photo
from app.states.photo import PhotoUploadStates


@pytest.mark.asyncio
async def test_handle_set_new_photo_clears_stale_fsm_context():
    message = AsyncMock()
    state = AsyncMock()

    await handle_set_new_photo(message, state)

    assert state.mock_calls[:2] == [
        call.clear(),
        call.set_state(PhotoUploadStates.waiting_for_main_photo),
    ]
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_set_partner_photo_clears_stale_fsm_context():
    message = AsyncMock()
    state = AsyncMock()

    await handle_set_partner_photo(message, state)

    assert state.mock_calls[:2] == [
        call.clear(),
        call.set_state(PhotoUploadStates.waiting_for_additional_photo),
    ]
    message.answer.assert_awaited_once()
