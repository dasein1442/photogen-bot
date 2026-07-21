from unittest.mock import AsyncMock

import pytest

from app.handlers.animate_photo import _do_photo_animation


@pytest.mark.asyncio
async def test_animation_delivery_sends_video_and_restores_menu():
    message = AsyncMock()
    analytics = AsyncMock()

    from unittest.mock import patch
    with (
        patch("app.handlers.animate_photo.backend.animate_photo", AsyncMock(return_value={"task_id": 42})),
        patch("app.handlers.animate_photo.backend.poll_task", AsyncMock(return_value={
            "status": "completed",
            "results": [{"status": "completed", "result_url": "https://cdn.example/video.mp4"}],
        })),
        patch("app.handlers.animate_photo.download_photo", AsyncMock(return_value=b"mp4")),
        patch("app.handlers.animate_photo.send_video", AsyncMock(return_value=type("Result", (), {"failed": 0})())) as send_video,
    ):
        await _do_photo_animation(
            message,
            photo_id=10,
            prompt="The subject smiles and turns toward the camera.",
            telegram_id=20,
            analytics=analytics,
        )

    send_video.assert_awaited_once_with(message, b"mp4", 20)
    analytics.track.assert_awaited()
    assert any("Готово" in str(call) for call in message.answer.await_args_list)
