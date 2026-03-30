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


@router.message(F.text == "✨ Изменить фото")
async def handle_custom_prompt_button(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь нажал 'Изменить фото' — просим отправить фото для редактирования."""
    await analytics.track("photoshop_opened", user_id=str(message.from_user.id))
    await state.clear()
    await state.set_state(PhotoUploadStates.waiting_for_photoshop_photo)
    await state.set_data({"photoshop_photo_ids": []})

    await message.answer(
        "✨ <b>Изменить фото</b>\n\n"
        "Отправь фото — и опиши, что хочешь получить. "
        "ИИ изменит что угодно: фон, одежду, внешность, атмосферу. "
        "А ещё — может сделать открытку, убрать лишнее или объединить людей с двух фото.\n\n"
        "📎 Отправь одну или две фотографии.\n\n"
        "<i>Стоимость: 2 генерации.</i>",
        parse_mode="HTML",
    )


@router.message(F.photo, PhotoUploadStates.waiting_for_photoshop_photo)
async def handle_photoshop_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил фото для ИИ-фотошопа — загружаем без face validation."""
    data = await state.get_data()
    photo_ids = data.get("photoshop_photo_ids", [])

    if len(photo_ids) >= 2:
        await message.answer("⚠️ Максимум 2 фото. Напиши промт для редактирования 👇")
        return

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

    photo_ids.append(result["photo_id"])
    await state.set_data({"photoshop_photo_ids": photo_ids})

    if len(photo_ids) == 1:
        await state.set_state(PhotoUploadStates.waiting_for_photoshop_photo_or_prompt)
        await message.answer(
            "✅ Фото загружено!\n\n"
            "Опиши, что хочешь получить — или отправь 2-е фото.\n"
            "Чем подробнее — тем лучше результат.\n\n"
            "<blockquote expandable><b>Примеры запросов:</b>\n\n"
            "• Замени фон на уютное кафе с тёплым вечерним светом\n"
            "• Переодень в чёрное вечернее платье с открытыми плечами\n"
            "• Сделай причёску — объёмные локоны медового оттенка\n"
            "• Убери всех людей на фоне, оставь только меня\n"
            "• Добавь снег, гирлянды и новогоднюю атмосферу\n"
            "• Сделай открытку с надписью «С Днём Рождения!»\n"
            "• Сделай лёгкий загар и голливудскую укладку\n\n"
            "💡 Можно отправить 2 фото и объединить их:\n"
            "• Поставь мужчину с фото 1 и девушку с фото 2 рядом\n"
            "• Возьми фон с первого фото, а человека со второго</blockquote>",
            parse_mode="HTML",
        )
    else:
        await state.set_state(PhotoUploadStates.waiting_for_custom_prompt)
        await message.answer(
            "Оба фото загружены! Опиши, что сделать 👇",
        )


@router.message(F.text, PhotoUploadStates.waiting_for_photoshop_photo)
async def handle_text_instead_of_photoshop_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил текст вместо фото — напоминаем."""
    menu_buttons = ("📸 Создать фотосессию", "Случайное фото", "Профиль", "Служба заботы", "Назад", "✨ Изменить фото", "💫 Новый образ", "🔍 Улучшить кач-во")
    if message.text.startswith("/") or message.text in menu_buttons:
        await state.clear()
        return
    await message.answer("📎 Сначала отправь фото, а потом напиши, что хочешь изменить.")


@router.message(F.photo, PhotoUploadStates.waiting_for_photoshop_photo_or_prompt)
async def handle_second_photoshop_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил второе фото."""
    await handle_photoshop_photo(message, state, analytics)


@router.message(F.text, PhotoUploadStates.waiting_for_photoshop_photo_or_prompt)
async def handle_prompt_after_first_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь написал промт после первого фото (без второго)."""
    await state.set_state(PhotoUploadStates.waiting_for_custom_prompt)
    await handle_custom_prompt_text(message, state, analytics)


@router.message(F.text, PhotoUploadStates.waiting_for_custom_prompt)
async def handle_custom_prompt_text(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил текст промта."""
    prompt = message.text.strip()

    # Проверяем, что это не команда или кнопка меню
    menu_buttons = ("📸 Создать фотосессию", "Случайное фото", "Профиль", "Служба заботы", "Назад", "✨ Изменить фото", "💫 Новый образ", "🔍 Улучшить кач-во")
    if prompt.startswith("/") or prompt in menu_buttons:
        await state.clear()
        return  # пусть другой хэндлер обработает

    if len(prompt) < 3:
        await message.answer("Промт слишком короткий. Напиши хотя бы несколько слов.")
        return

    if len(prompt) > 1000:
        await message.answer("Промт слишком длинный (максимум 1000 символов). Сократи и отправь снова.")
        return

    data = await state.get_data()
    photo_ids = data.get("photoshop_photo_ids", [])
    if not photo_ids:
        await state.clear()
        await message.answer("⚠️ Фото не найдено. Начни сначала — нажми «✨ Изменить фото».", reply_markup=get_main_menu_keyboard())
        return

    await state.clear()
    await analytics.track("custom_prompt_submitted", user_id=str(message.from_user.id), properties={"prompt_length": len(prompt), "photo_count": len(photo_ids)})

    await _do_custom_prompt_generation(message, prompt, photo_ids=photo_ids, analytics=analytics)


async def _do_custom_prompt_generation(
    message: Message, prompt: str, photo_ids: list[int],
    telegram_id: int | None = None, analytics: AnalyticsClient | None = None,
):
    """Запуск генерации по кастомному промту → поллинг → отправка результата."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("✨ Генерирую фото по твоему промту, подожди немного...")

    # 1. Запуск генерации
    try:
        gen_result = await backend.generate_custom_prompt(telegram_id=telegram_id, prompt=prompt, photo_ids=photo_ids)
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

    if gen_result.get("error") == "already_generating":
        await message.answer("⏳ Подожди — предыдущая генерация ещё в процессе.")
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
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] custom_prompt: refund failed: {re}", exc_info=True)
            return

        logger.info(f"[tg={telegram_id}] custom_prompt: скачано {len(photo_data)} байт, отправляю в Telegram")
        send_result = await send_photos(message, [photo_data], telegram_id)

        if analytics:
            await analytics.track("custom_prompt_generation_delivered", user_id=str(telegram_id), properties={"task_id": task_id, "success": send_result.failed == 0})

        if send_result.failed > 0:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] custom_prompt: refund failed: {re}", exc_info=True)

        total_time = time.monotonic() - t_total
        logger.info(f"[tg={telegram_id}] Custom prompt generation total={total_time:.2f}s")

        await message.answer(
            "✨ Готово! Хочешь ещё — просто нажми «✨ Изменить фото» снова.",
            reply_markup=get_main_menu_keyboard(),
        )
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
        if task_id:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
                logger.info(f"[tg={telegram_id}] custom_prompt: refunded 2 generations for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] custom_prompt: timeout refund failed: {refund_err}", exc_info=True)
