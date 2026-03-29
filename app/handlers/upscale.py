import logging
import time

from aiogram import F, Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient
from app.services.tg_sender import download_photo, send_photos
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_buy_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "🔍 Улучшить кач-во")
async def handle_upscale_button(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь нажал 'Улучшить кач-во' — просим отправить фото."""
    await analytics.track("upscale_opened", user_id=str(message.from_user.id))
    await state.clear()
    await state.set_state(PhotoUploadStates.waiting_for_upscale_photo)

    await message.answer(
        "🔍 <b>Улучшить качество</b>\n\n"
        "ИИ увеличит разрешение и восстановит детали — размытое или сжатое фото станет чётким и качественным.\n\n"
        "📎 Отправь фотографию, которую нужно улучшить.\n\n"
        "<i>Стоимость: 2 генерации.</i>",
        parse_mode="HTML",
    )


@router.message(F.photo, PhotoUploadStates.waiting_for_upscale_photo)
async def handle_upscale_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил фото для апскейла — загружаем и запускаем."""
    await state.clear()

    await message.answer("🔄 Загружаю фото...")

    photo = message.photo[-1]
    telegram_id = message.from_user.id

    # Скачиваем фото из Telegram
    try:
        bot = message.bot
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        photo_data = file_bytes.read()
    except Exception as e:
        logger.error(f"Ошибка скачивания фото из Telegram: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось скачать фото. Попробуй ещё раз.")
        return

    # Загружаем на бэкенд (без face validation)
    try:
        upload_result = await backend.upload_photo_raw(
            telegram_id=telegram_id,
            photo_bytes=photo_data,
            filename=f"{telegram_id}_{photo.file_id}.jpg",
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото на бэкенд: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось загрузить фото. Попробуй позже.")
        return

    if not upload_result.get("ok"):
        error = upload_result.get("error", "Неизвестная ошибка")
        await message.answer(f"⚠️ {error}")
        return

    photo_id = upload_result["photo_id"]

    await analytics.track("upscale_photo_uploaded", user_id=str(telegram_id))

    await _do_upscale(message, photo_id=photo_id, analytics=analytics)


async def _do_upscale(
    message: Message, photo_id: int,
    telegram_id: int | None = None, analytics: AnalyticsClient | None = None,
):
    """Запуск апскейла → поллинг → отправка результата."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id
    assert telegram_id is not None

    await message.answer("🔍 Улучшаю качество фото, подожди немного...")

    # 1. Запуск
    try:
        gen_result = await backend.upscale_photo(telegram_id=telegram_id, photo_id=photo_id)
    except Exception as e:
        logger.error(f"Ошибка запуска апскейла: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось запустить улучшение. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        if analytics:
            await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "no_balance_upscale"})
        await message.answer(
            "❌ У тебя закончились генерации!\n\n"
            "Пополни баланс, чтобы продолжить.",
            reply_markup=get_buy_keyboard(),
        )
        return

    if gen_result.get("error") == "already_generating":
        await message.answer("⏳ Подожди — предыдущая генерация ещё в процессе.")
        return

    if gen_result.get("error") == "photo_not_found":
        await message.answer("⚠️ Фото не найдено. Отправь его ещё раз, и я попробую снова.")
        return

    task_id = gen_result.get("task_id")
    if not task_id:
        await message.answer("⚠️ Не удалось запустить улучшение. Попробуй позже.")
        return

    # 2. Поллинг
    try:
        task_result = await backend.poll_task(task_id)
    except Exception as e:
        logger.error(f"Ошибка поллинга задачи {task_id}: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка при ожидании результата. Попробуй позже.")
        return

    status = task_result.get("status")

    if status == "completed":
        results = task_result.get("results", [])
        successful = [r for r in results if r.get("status") == "completed" and r.get("result_url")]

        if not successful:
            await message.answer("❌ Улучшение не удалось. Попробуй ещё раз.")
            return

        url = successful[0]["result_url"]
        logger.info(f"[tg={telegram_id}] upscale: скачиваю фото, url={url[:120]}")
        try:
            photo_data = await download_photo(url)
        except Exception as e:
            logger.error(f"[tg={telegram_id}] upscale: download failed: {e}", exc_info=True)
            await message.answer("Не удалось скачать фото. Попробуй позже.")
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] upscale: refund failed: {re}", exc_info=True)
            return

        logger.info(f"[tg={telegram_id}] upscale: скачано {len(photo_data)} байт, отправляю в Telegram")

        # Отправляем как документ для максимального качества
        from aiogram.types import BufferedInputFile
        try:
            doc = BufferedInputFile(photo_data, filename="upscaled.jpg")
            await message.answer_document(doc, caption="🔍 Фото в улучшенном качестве")
        except Exception as e:
            logger.warning(f"[tg={telegram_id}] upscale: document send failed, trying as photo: {e}")
            send_result = await send_photos(message, [photo_data], telegram_id)
            if send_result.failed > 0:
                try:
                    await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
                except Exception as re:
                    logger.error(f"[tg={telegram_id}] upscale: refund failed: {re}", exc_info=True)

        if analytics:
            await analytics.track("upscale_delivered", user_id=str(telegram_id), properties={"task_id": task_id})

        total_time = time.monotonic() - t_total
        logger.info(f"[tg={telegram_id}] Upscale total={total_time:.2f}s")

        await message.answer(
            "✅ Готово! Хочешь ещё — нажми «🔍 Улучшить кач-во» снова.",
            reply_markup=get_main_menu_keyboard(),
        )
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Улучшение не удалось: {error_msg}")
    else:
        await message.answer("⏰ Улучшение заняло слишком много времени. Попробуй позже.")
        if task_id:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
                logger.info(f"[tg={telegram_id}] upscale: refunded 2 generations for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] upscale: timeout refund failed: {refund_err}", exc_info=True)
