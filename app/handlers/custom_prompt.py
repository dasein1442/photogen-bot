import logging
import time

from aiogram import F, Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient
from app.services.generation_lock import acquire as lock_acquire, release as lock_release
from app.services.tg_sender import download_photo, send_photos
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_buy_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "ИИ-фотошоп")
async def handle_custom_prompt_button(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь нажал 'ИИ-фотошоп' — просим отправить фото для редактирования."""
    await analytics.track("photoshop_opened", user_id=str(message.from_user.id))
    await state.clear()
    await state.set_state(PhotoUploadStates.waiting_for_photoshop_photo)

    await message.answer(
        "📸 Отправь фото, которое хочешь отредактировать.\n\n"
        "Стоимость: 1 генерация с баланса.",
    )


@router.message(F.photo, PhotoUploadStates.waiting_for_photoshop_photo)
async def handle_photoshop_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил фото для ИИ-фотошопа — загружаем без face validation."""
    await message.answer("🔄 Загружаю фото...")

    photo = message.photo[-1]

    try:
        bot = message.bot
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        photo_data = file_bytes.read()
    except Exception as e:
        logger.error(f"Ошибка скачивания фото из Telegram: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось скачать фото. Попробуй ещё раз.")
        return

    try:
        result = await backend.upload_photo_raw(
            telegram_id=message.from_user.id,
            photo_bytes=photo_data,
            filename=f"{message.from_user.id}_{photo.file_id}.jpg",
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото на бэкенд: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось загрузить фото. Попробуй позже.")
        return

    if not result.get("ok"):
        error = result.get("error", "Неизвестная ошибка")
        await message.answer(f"⚠️ {error}")
        return

    photo_id = result["photo_id"]
    await state.set_data({"photoshop_photo_id": photo_id})
    await state.set_state(PhotoUploadStates.waiting_for_custom_prompt)

    await message.answer(
        "🎨 Фото загружено! Напиши, что изменить:\n\n"
        "• «Сделай белый фон»\n"
        "• «Поменяй причёску на каре»\n"
        "• «Надень чёрную кожаную куртку»\n"
        "• «Убери фон и оставь только меня»\n\n"
        "Пиши 👇",
    )


@router.message(F.text, PhotoUploadStates.waiting_for_custom_prompt)
async def handle_custom_prompt_text(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил текст промта."""
    prompt = message.text.strip()

    # Проверяем, что это не команда или кнопка меню
    if prompt.startswith("/") or prompt in ("Фотосессии", "Случайное фото", "Профиль", "Служба заботы", "Назад", "ИИ-фотошоп"):
        await state.clear()
        return  # пусть другой хэндлер обработает

    if len(prompt) < 3:
        await message.answer("Промт слишком короткий. Напиши хотя бы несколько слов.")
        return

    if len(prompt) > 1000:
        await message.answer("Промт слишком длинный (максимум 1000 символов). Сократи и отправь снова.")
        return

    data = await state.get_data()
    photo_id = data.get("photoshop_photo_id")
    if not photo_id:
        await state.clear()
        await message.answer("⚠️ Фото не найдено. Начни сначала — нажми «ИИ-фотошоп».", reply_markup=get_main_menu_keyboard())
        return

    await state.clear()
    await analytics.track("custom_prompt_submitted", user_id=str(message.from_user.id), properties={"prompt_length": len(prompt)})

    await _do_custom_prompt_generation(message, prompt, photo_id=photo_id, analytics=analytics)


async def _do_custom_prompt_generation(
    message: Message, prompt: str, photo_id: int,
    telegram_id: int | None = None, analytics: AnalyticsClient | None = None,
):
    """Запуск генерации по кастомному промту → поллинг → отправка результата."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id

    if not lock_acquire(telegram_id):
        await message.answer("⏳ Подожди — предыдущая генерация ещё в процессе.")
        return

    await message.answer("✨ Генерирую фото по твоему промту, подожди немного...")

    try:
        await _do_custom_prompt_inner(message, prompt, photo_id, telegram_id, t_total, analytics)
    finally:
        lock_release(telegram_id)


async def _do_custom_prompt_inner(
    message: Message, prompt: str, photo_id: int,
    telegram_id: int, t_total: float, analytics: AnalyticsClient | None,
):
    # 1. Запуск генерации
    try:
        gen_result = await backend.generate_custom_prompt(telegram_id=telegram_id, prompt=prompt, photo_id=photo_id)
    except Exception as e:
        logger.error(f"Ошибка запуска кастомной генерации: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        if analytics:
            await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "no_balance_custom_prompt"})
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
            await message.answer("❌ Генерация не удалась. Попробуй ещё раз.")
            return

        url = successful[0]["result_url"]
        logger.info(f"[tg={telegram_id}] custom_prompt: скачиваю фото, url={url[:120]}")
        try:
            photo_data = await download_photo(url)
        except Exception as e:
            logger.error(f"[tg={telegram_id}] custom_prompt: download failed: {e}", exc_info=True)
            await message.answer("Не удалось скачать фото. Попробуй позже.")
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] custom_prompt: refund failed: {re}", exc_info=True)
            return

        logger.info(f"[tg={telegram_id}] custom_prompt: скачано {len(photo_data)} байт, отправляю в Telegram")
        send_result = await send_photos(message, [photo_data], telegram_id)

        if analytics:
            await analytics.track("custom_prompt_generation_delivered", user_id=str(telegram_id), properties={"task_id": task_id, "success": send_result.failed == 0})

        if send_result.failed > 0:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] custom_prompt: refund failed: {re}", exc_info=True)

        total_time = time.monotonic() - t_total
        logger.info(f"[tg={telegram_id}] Custom prompt generation total={total_time:.2f}s")

        await message.answer(
            "✨ Готово! Хочешь ещё — просто нажми «ИИ-фотошоп» снова.",
            reply_markup=get_main_menu_keyboard(),
        )
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
        if task_id:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
                logger.info(f"[tg={telegram_id}] custom_prompt: refunded 1 generation for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] custom_prompt: timeout refund failed: {refund_err}", exc_info=True)
