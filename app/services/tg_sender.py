import asyncio
import logging
from dataclasses import dataclass

import aiohttp
from aiogram.types import Message, BufferedInputFile, InputMediaPhoto
from aiogram.exceptions import (
    TelegramRetryAfter,
    TelegramNetworkError,
    TelegramBadRequest,
    TelegramForbiddenError,
)

logger = logging.getLogger(__name__)

# Per-user locks to prevent parallel media group sends to the same chat.
# Telegram API can't handle concurrent media groups to one user reliably.
_user_locks: dict[int, asyncio.Lock] = {}

# Global semaphore to limit total concurrent uploads across all users
_global_send_semaphore = asyncio.Semaphore(4)


def _get_user_lock(telegram_id: int) -> asyncio.Lock:
    if telegram_id not in _user_locks:
        _user_locks[telegram_id] = asyncio.Lock()
    return _user_locks[telegram_id]


@dataclass
class SendResult:
    total: int           # how many photos were attempted
    sent: int            # how many successfully sent
    failed: int          # how many failed to send
    user_blocked: bool   # True if TelegramForbiddenError received


async def download_photo(url: str) -> bytes:
    """Download photo by URL. Returns bytes. Raises on error."""
    logger.info(f"[download] Starting download: {url[:120]}...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            logger.info(f"[download] HTTP {resp.status}, content-type={resp.content_type}, content-length={resp.content_length}")
            resp.raise_for_status()
            data = await resp.read()
            logger.info(f"[download] Downloaded {len(data)} bytes")
            return data


async def send_photos(message: Message, photos_data: list[bytes], telegram_id: int) -> SendResult:
    """Send photos to Telegram with retry + single-photo fallback.

    Uses per-user lock to prevent parallel media group sends to the same chat,
    which causes Telegram API to return 400 and potentially deliver duplicates.

    Returns SendResult with accurate counts of sent/failed photos.
    """
    total = len(photos_data)
    max_retries = 3
    delays = [5, 15, 30]
    user_lock = _get_user_lock(telegram_id)

    if user_lock.locked():
        logger.info(f"[tg={telegram_id}] Waiting for per-user send lock (another send in progress)")
    async with user_lock:
        logger.info(f"[tg={telegram_id}] Acquired per-user lock, sending {total} photos")
        for attempt in range(max_retries):
            try:
                async with _global_send_semaphore:
                    if len(photos_data) == 1:
                        await message.answer_photo(
                            photo=BufferedInputFile(photos_data[0], filename="photo.jpg"),
                        )
                    else:
                        media = [
                            InputMediaPhoto(
                                media=BufferedInputFile(data, filename=f"photo_{i}.jpg"),
                            )
                            for i, data in enumerate(photos_data)
                        ]
                        await message.answer_media_group(media=media)
                return SendResult(total=total, sent=total, failed=0, user_blocked=False)
            except TelegramForbiddenError as e:
                logger.error(
                    f"[tg={telegram_id}] Bot blocked by user: {e}", exc_info=True
                )
                return SendResult(total=total, sent=0, failed=total, user_blocked=True)
            except TelegramRetryAfter as e:
                logger.warning(
                    f"[tg={telegram_id}] Send attempt {attempt + 1} rate limited, "
                    f"retry_after={e.retry_after}s"
                )
                await asyncio.sleep(e.retry_after)
                continue
            except TelegramBadRequest as e:
                # 400 is a permanent error — don't retry, go straight to fallback.
                # Retrying risks duplicate delivery (Telegram may have already processed the request).
                logger.warning(
                    f"[tg={telegram_id}] Send attempt {attempt + 1} bad request: {e}, "
                    f"falling back to single-photo mode", exc_info=True,
                )
                break
            except TelegramNetworkError as e:
                # Network error means connection dropped — but Telegram may have already
                # received and delivered the photos. Don't retry media group to avoid duplicates.
                logger.warning(
                    f"[tg={telegram_id}] Send attempt {attempt + 1} network error: {e}, "
                    f"falling back to single-photo mode", exc_info=True,
                )
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"[tg={telegram_id}] Send attempt {attempt + 1} failed: {e}, "
                        f"retrying in {delays[attempt]}s",
                    )
                    await asyncio.sleep(delays[attempt])
                else:
                    logger.error(
                        f"[tg={telegram_id}] All {max_retries} send attempts failed: {e}",
                        exc_info=True,
                    )

        else:
            # All retries exhausted without break — only generic Exception path gets here
            pass

        # Fallback: send photos one by one
        logger.info(f"[tg={telegram_id}] Fallback: sending {len(photos_data)} photos one by one")
        sent = 0
        for i, data in enumerate(photos_data):
            try:
                async with _global_send_semaphore:
                    await message.answer_photo(
                        photo=BufferedInputFile(data, filename=f"photo_{i}.jpg"),
                    )
                sent += 1
            except TelegramForbiddenError as e:
                logger.error(
                    f"[tg={telegram_id}] Bot blocked by user during fallback: {e}",
                    exc_info=True,
                )
                return SendResult(
                    total=total, sent=sent, failed=total - sent, user_blocked=True
                )
            except TelegramRetryAfter as e:
                logger.warning(
                    f"[tg={telegram_id}] Fallback photo {i} rate limited, "
                    f"retry_after={e.retry_after}s"
                )
                await asyncio.sleep(e.retry_after)
                try:
                    async with _global_send_semaphore:
                        await message.answer_photo(
                            photo=BufferedInputFile(data, filename=f"photo_{i}.jpg"),
                        )
                    sent += 1
                except Exception as retry_e:
                    logger.error(
                        f"[tg={telegram_id}] Fallback photo {i} retry after rate limit failed: {retry_e}",
                        exc_info=True,
                    )
            except TelegramBadRequest as e:
                logger.error(
                    f"[tg={telegram_id}] Fallback photo {i} bad request (skipped): {e}",
                    exc_info=True,
                )
            except TelegramNetworkError as e:
                logger.error(
                    f"[tg={telegram_id}] Fallback photo {i} network error: {e}",
                    exc_info=True,
                )
            except Exception as e:
                logger.error(
                    f"[tg={telegram_id}] Failed to send photo {i}: {e}", exc_info=True
                )

        failed = total - sent
        if sent == 0:
            await message.answer("Не удалось отправить фото. Попробуй запросить генерацию ещё раз.")
        elif sent < total:
            logger.warning(f"[tg={telegram_id}] Sent {sent}/{total} photos in fallback mode")

        return SendResult(total=total, sent=sent, failed=failed, user_blocked=False)
