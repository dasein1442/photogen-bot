"""Tests for _send_photos retry/fallback logic."""
import asyncio
from unittest.mock import AsyncMock, patch, call

import pytest

from app.handlers.generation import _send_photos, _tg_send_semaphore


@pytest.fixture
def mock_message():
    msg = AsyncMock()
    msg.answer_photo = AsyncMock()
    msg.answer_media_group = AsyncMock()
    msg.answer = AsyncMock()
    return msg


PHOTO_1 = b"\xff\xd8photo_1_data"
PHOTO_2 = b"\xff\xd8photo_2_data"
PHOTO_3 = b"\xff\xd8photo_3_data"
TG_ID = 123456


class TestSendPhotosSinglePhoto:
    """Single photo uses answer_photo, not answer_media_group."""

    @pytest.mark.asyncio
    async def test_single_photo_success(self, mock_message):
        await _send_photos(mock_message, [PHOTO_1], TG_ID)

        mock_message.answer_photo.assert_called_once()
        mock_message.answer_media_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_photo_retry_then_success(self, mock_message):
        mock_message.answer_photo.side_effect = [Exception("timeout"), None]

        with patch("app.handlers.generation.asyncio.sleep", new_callable=AsyncMock):
            await _send_photos(mock_message, [PHOTO_1], TG_ID)

        assert mock_message.answer_photo.call_count == 2


class TestSendPhotosMultiplePhotos:
    """Multiple photos use answer_media_group."""

    @pytest.mark.asyncio
    async def test_media_group_success(self, mock_message):
        await _send_photos(mock_message, [PHOTO_1, PHOTO_2], TG_ID)

        mock_message.answer_media_group.assert_called_once()
        mock_message.answer_photo.assert_not_called()


class TestSendPhotosRetry:
    """Retry logic: 3 attempts with delays."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, mock_message):
        """Fails first attempt, succeeds on second."""
        mock_message.answer_media_group.side_effect = [Exception("timeout"), None]

        with patch("app.handlers.generation.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _send_photos(mock_message, [PHOTO_1, PHOTO_2], TG_ID)

        assert mock_message.answer_media_group.call_count == 2
        mock_sleep.assert_called_once_with(5)  # first delay

    @pytest.mark.asyncio
    async def test_retry_delays_are_correct(self, mock_message):
        """Fails 3 times, check that delays are 5, 15 (third has no delay — goes to fallback)."""
        mock_message.answer_media_group.side_effect = [
            Exception("timeout"),
            Exception("timeout"),
            Exception("timeout"),
        ]
        # Fallback single sends also fail
        mock_message.answer_photo.side_effect = Exception("also broken")

        with patch("app.handlers.generation.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _send_photos(mock_message, [PHOTO_1, PHOTO_2], TG_ID)

        # Only 2 sleeps: before retry 2 (5s) and before retry 3 (15s)
        assert mock_sleep.call_args_list == [call(5), call(15)]

    @pytest.mark.asyncio
    async def test_user_notified_on_retry(self, mock_message):
        """User gets a message about slow sending on retry."""
        mock_message.answer_media_group.side_effect = [Exception("timeout"), None]

        with patch("app.handlers.generation.asyncio.sleep", new_callable=AsyncMock):
            await _send_photos(mock_message, [PHOTO_1, PHOTO_2], TG_ID)

        # Check that the "retrying" message was sent
        mock_message.answer.assert_any_call(
            "⏳ Отправка фото заняла слишком долго, пробую ещё раз..."
        )


class TestSendPhotosFallback:
    """After 3 failed media_group attempts, falls back to one-by-one."""

    @pytest.mark.asyncio
    async def test_fallback_sends_individually(self, mock_message):
        """All media_group retries fail -> sends photos one by one."""
        mock_message.answer_media_group.side_effect = Exception("always fails")
        mock_message.answer_photo.side_effect = [None, None, None]

        with patch("app.handlers.generation.asyncio.sleep", new_callable=AsyncMock):
            await _send_photos(mock_message, [PHOTO_1, PHOTO_2, PHOTO_3], TG_ID)

        assert mock_message.answer_media_group.call_count == 3
        assert mock_message.answer_photo.call_count == 3

    @pytest.mark.asyncio
    async def test_fallback_partial_success(self, mock_message):
        """Fallback: 2 out of 3 photos sent successfully."""
        mock_message.answer_media_group.side_effect = Exception("always fails")
        mock_message.answer_photo.side_effect = [None, Exception("fail"), None]

        with patch("app.handlers.generation.asyncio.sleep", new_callable=AsyncMock):
            await _send_photos(mock_message, [PHOTO_1, PHOTO_2, PHOTO_3], TG_ID)

        assert mock_message.answer_photo.call_count == 3
        # No error message — partial success (2/3 sent)
        error_calls = [
            c for c in mock_message.answer.call_args_list
            if "Не удалось отправить" in str(c)
        ]
        assert len(error_calls) == 0

    @pytest.mark.asyncio
    async def test_fallback_all_fail_notifies_user(self, mock_message):
        """Everything fails -> user gets error message."""
        mock_message.answer_media_group.side_effect = Exception("always fails")
        mock_message.answer_photo.side_effect = Exception("also fails")

        with patch("app.handlers.generation.asyncio.sleep", new_callable=AsyncMock):
            await _send_photos(mock_message, [PHOTO_1, PHOTO_2], TG_ID)

        mock_message.answer.assert_any_call(
            "⚠️ Не удалось отправить фото. Попробуй запросить генерацию ещё раз."
        )


class TestSemaphore:
    """Semaphore limits concurrent sends."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self, mock_message):
        """At most 2 sends happen concurrently."""
        max_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        original_answer_photo = mock_message.answer_photo

        async def slow_send(*args, **kwargs):
            nonlocal max_concurrent, current
            async with lock:
                current += 1
                max_concurrent = max(max_concurrent, current)
            await asyncio.sleep(0.05)
            async with lock:
                current -= 1

        mock_message.answer_photo.side_effect = slow_send

        # Launch 4 concurrent sends of single photos
        tasks = [
            asyncio.create_task(_send_photos(mock_message, [PHOTO_1], TG_ID))
            for _ in range(4)
        ]
        await asyncio.gather(*tasks)

        assert max_concurrent <= 2
