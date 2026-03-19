import asyncio
import logging
import time

from aiogram import Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient
from app.services.tg_sender import download_photo, send_photos, SendResult
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_buy_keyboard

logger = logging.getLogger(__name__)
router = Router()


def _format_validation_errors(errors: list[str]) -> str:
    """Форматировать список ошибок валидации в читаемое сообщение."""
    if not errors:
        return "❌ Неизвестная ошибка. Попробуй другое фото."

    lines = ["❌ Фото не прошло проверку:\n"]
    for err in errors:
        lines.append(f"• {err}")
    lines.append("\nИсправь замечания и отправь другое фото.")
    return "\n".join(lines)


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_gen_"))
async def handle_photosession_choice(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь нажал 'Начать генерацию' в детальном виде фотосессии."""
    photosession_id = int(callback.data.split("_")[2])
    await analytics.track("photosession_selected", user_id=str(callback.from_user.id), properties={"photosession_id": photosession_id})

    # Проверяем, установлено ли фото профиля
    try:
        user_data = await backend.get_user(telegram_id=callback.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя: {e}", exc_info=True)
        await callback.message.answer("⚠️ Не удалось получить данные. Попробуй позже.")
        await callback.answer()
        return

    profile_photo_id = user_data.get("user", {}).get("profile_photo_id")

    if profile_photo_id:
        # Фото профиля есть — сразу генерируем
        await callback.answer()
        await _do_generation(callback.message, photosession_id, callback.from_user.id, analytics=analytics)
    else:
        # Фото профиля нет — просим загрузить
        await state.set_data({"photosession_id": photosession_id})
        await state.set_state(PhotoUploadStates.waiting_for_main_photo)

        await callback.message.answer(
            "📸 Для генерации нужно фото профиля.\n\n"
            "Отправь своё фото в чат — оно будет сохранено и использовано "
            "для всех будущих генераций.\n\n"
            "**Несколько важных моментов к фото:**\n"
            "• Используй крупный план (лучше селфи).\n"
            "• Без других людей и животных.\n"
            "• Лицо нейтральное или с лёгкой улыбкой.\n"
            "• Голова прямо, без наклонов.\n"
            "• Без очков и аксессуаров на лице.\n"
            "• Хорошее освещение — залог качественного результата.",
            parse_mode="Markdown",
        )
        await callback.answer()


async def _do_generation(message: Message, photosession_id: int, telegram_id: int | None = None, analytics: AnalyticsClient | None = None):
    """Запуск генерации → поллинг → отправка результатов."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("⏳ Начинаю генерацию, подожди немного...")

    # 1. Запуск генерации на бэкенде
    t0 = time.monotonic()
    try:
        gen_result = await backend.generate_photo(
            telegram_id=telegram_id,
            photosession_id=photosession_id,
        )
    except Exception as e:
        logger.error(
            f"Ошибка запуска генерации: {type(e).__name__}: {e} "
            f"(telegram_id={telegram_id}, photosession_id={photosession_id})",
            exc_info=True,
        )
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return
    api_time = time.monotonic() - t0
    logger.info(f"[tg={telegram_id}] Backend /generate responded in {api_time:.2f}s")

    if gen_result.get("error") == "no_balance":
        if analytics:
            await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "no_balance_photosession"})
        await message.answer(
            "❌ У тебя закончились генерации!\n\n"
            "Пополни баланс, чтобы продолжить создавать фото.",
            reply_markup=get_buy_keyboard(),
        )
        return

    task_id = gen_result.get("task_id")
    if not task_id:
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    # 2. Поллинг результата
    t0 = time.monotonic()
    try:
        task_result = await backend.poll_task(task_id)
    except Exception as e:
        logger.error(f"Ошибка поллинга задачи {task_id}: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка при ожидании результата. Попробуй позже.")
        return
    poll_time = time.monotonic() - t0
    logger.info(f"[tg={telegram_id}] Polling task_id={task_id} took {poll_time:.2f}s, status={task_result.get('status')}")

    status = task_result.get("status")

    if status == "completed":
        results = task_result.get("results", [])
        successful = [r for r in results if r.get("status") == "completed" and r.get("result_url")]
        failed = [r for r in results if r.get("status") == "failed"]
        total = len(results)

        if not successful:
            await message.answer("❌ Все генерации не удались. Попробуй ещё раз.")
            return

        # 3. Скачиваем фото с S3 (параллельно)
        t0 = time.monotonic()
        logger.info(f"[tg={telegram_id}] Downloading {len(successful)} photos from S3...")
        for i, r in enumerate(successful):
            logger.info(f"[tg={telegram_id}] result[{i}]: status={r.get('status')}, url={r.get('result_url', 'NO_URL')[:120]}")

        download_results = await asyncio.gather(
            *[download_photo(r["result_url"]) for r in successful],
            return_exceptions=True,
        )

        # Filter out download failures
        photos_data = []
        download_failed = 0
        for i, result in enumerate(download_results):
            if isinstance(result, Exception):
                logger.error(
                    f"[tg={telegram_id}] Failed to download photo {i}: {result}",
                    exc_info=result,
                )
                download_failed += 1
            else:
                photos_data.append(result)

        if not photos_data:
            logger.error(f"[tg={telegram_id}] All {len(download_results)} downloads failed", exc_info=True)
            await message.answer("Не удалось скачать фото. Попробуй позже.")
            try:
                await backend.refund_delivery(
                    telegram_id=telegram_id,
                    task_id=task_id,
                    failed_count=len(successful),
                )
            except Exception as e:
                logger.error(f"[tg={telegram_id}] Refund request failed: {e}", exc_info=True)
            return

        download_time = time.monotonic() - t0
        logger.info(
            f"[tg={telegram_id}] Downloaded {len(photos_data)} photos in {download_time:.2f}s, "
            f"sizes: {[len(d) for d in photos_data]}"
        )

        # 4. Отправляем в Telegram (с retry + fallback)
        t0 = time.monotonic()
        logger.info(f"[tg={telegram_id}] Sending {len(photos_data)} photos to Telegram...")
        send_result: SendResult = await send_photos(message, photos_data, telegram_id)

        total_failed = download_failed + send_result.failed
        if total_failed > 0:
            logger.warning(
                f"[tg={telegram_id}] Delivery incomplete: "
                f"download_failed={download_failed}, send_failed={send_result.failed}"
            )
            try:
                await backend.refund_delivery(
                    telegram_id=telegram_id,
                    task_id=task_id,
                    failed_count=total_failed,
                )
                logger.info(f"[tg={telegram_id}] Refunded {total_failed} generations for delivery failure")
            except Exception as e:
                logger.error(f"[tg={telegram_id}] Refund request failed: {e}", exc_info=True)

        tg_send_time = time.monotonic() - t0
        logger.info(f"[tg={telegram_id}] Telegram send took {tg_send_time:.2f}s")

        if analytics:
            await analytics.track("generation_delivered", user_id=str(telegram_id), properties={"task_id": task_id, "total": send_result.total, "sent": send_result.sent, "failed": send_result.failed})

        total_time = time.monotonic() - t_total
        logger.info(
            f"[tg={telegram_id}] Generation complete: "
            f"api={api_time:.2f}s, poll={poll_time:.2f}s, download={download_time:.2f}s, "
            f"tg_send={tg_send_time:.2f}s, total={total_time:.2f}s, ok={len(successful)}/{total}"
        )

        # Сообщаем о неудачных
        if failed:
            await message.answer(
                f"⚠️ {len(failed)} из {total} фото не удалось сгенерировать. "
                "Кредиты за них возвращены."
            )

        await message.answer(
            "😍 Смотри, какая красота!\n\n"
            "Как тебе результат?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="👍 Нравится", callback_data=f"photo_feedback:ps:{task_id}:like"),
                    InlineKeyboardButton(text="👎 Не нравится", callback_data=f"photo_feedback:ps:{task_id}:dislike"),
                ],
            ]),
        )
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
        if task_id:
            logger.error(f"[tg={telegram_id}] Poll timeout for task_id={task_id}, attempting refund", exc_info=True)
            try:
                task_data = await backend.get_task_status(task_id)
                results = task_data.get("results", [])
                # Refund for all results that are not already refunded (failed status is refunded by backend)
                completed_count = sum(1 for r in results if r.get("status") == "completed") if results else 0
                pending_count = sum(1 for r in results if r.get("status") in ("pending", "processing")) if results else 0
                refund_count = completed_count + pending_count
                if refund_count == 0:
                    refund_count = 1  # At minimum, refund 1 credit
                await backend.refund_delivery(
                    telegram_id=telegram_id,
                    task_id=task_id,
                    failed_count=refund_count,
                )
                logger.info(f"[tg={telegram_id}] Refunded {refund_count} generations for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] Timeout refund failed: {refund_err}", exc_info=True)
