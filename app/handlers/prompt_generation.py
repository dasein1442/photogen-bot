"""Handler for 'Генерация по промту' feature.

Flow: user sends photo(s) → writes prompt → Gemini rewrites prompt → Seedream generates photo.
"""
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


@router.message(F.text == "Генерация по промту")
async def handle_prompt_gen_button(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """User clicked 'Генерация по промту' — ask for photo."""
    await analytics.track("prompt_generation_opened", user_id=str(message.from_user.id))
    await state.clear()
    await state.set_state(PhotoUploadStates.waiting_for_prompt_gen_photo)
    await state.set_data({"prompt_gen_photo_ids": []})

    await message.answer(
        "🎨 Генерация по промту\n\n"
        "Отправь фото (до 2 штук), а затем опиши, что хочешь получить.\n"
        "Я обработаю твой запрос через ИИ и сгенерирую результат.\n\n"
        "Стоимость: 2 генерации с баланса.\n\n"
        "Отправь фото 👇",
    )


@router.message(F.photo, PhotoUploadStates.waiting_for_prompt_gen_photo)
async def handle_prompt_gen_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """User sent photo for prompt generation."""
    data = await state.get_data()
    photo_ids = data.get("prompt_gen_photo_ids", [])

    if len(photo_ids) >= 2:
        await message.answer("⚠️ Максимум 2 фото. Напиши свой запрос 👇")
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
    await state.set_data({"prompt_gen_photo_ids": photo_ids})

    if len(photo_ids) == 1:
        await state.set_state(PhotoUploadStates.waiting_for_prompt_gen_text)
        await message.answer(
            "📸 Фото загружено!\n\n"
            "Можешь отправить ещё одно фото или сразу написать свой запрос.\n\n"
            "Например:\n"
            "• «Сделай в стиле аниме»\n"
            "• «Перенеси на пляж с закатом»\n"
            "• «Сделай как картину маслом»\n\n"
            "Пиши или отправь ещё фото 👇",
        )
    else:
        await state.set_state(PhotoUploadStates.waiting_for_prompt_gen_text)
        await message.answer(
            "📸 Оба фото загружены! Напиши свой запрос 👇",
        )


@router.message(F.photo, PhotoUploadStates.waiting_for_prompt_gen_text)
async def handle_prompt_gen_second_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """User sends second photo while in text-waiting state."""
    data = await state.get_data()
    photo_ids = data.get("prompt_gen_photo_ids", [])
    if len(photo_ids) >= 2:
        await message.answer("⚠️ Максимум 2 фото. Напиши свой запрос 👇")
        return
    # Redirect to photo handler
    await handle_prompt_gen_photo(message, state, analytics)


@router.message(F.text, PhotoUploadStates.waiting_for_prompt_gen_text)
async def handle_prompt_gen_text(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """User sent prompt text for generation."""
    prompt = message.text.strip()

    menu_buttons = ("Фотосессии", "Случайное фото", "Профиль", "Служба заботы", "Назад", "ИИ-фотошоп", "Генерация по промту")
    if prompt.startswith("/") or prompt in menu_buttons:
        await state.clear()
        return

    if len(prompt) < 3:
        await message.answer("Запрос слишком короткий. Напиши хотя бы несколько слов.")
        return

    if len(prompt) > 1000:
        await message.answer("Запрос слишком длинный (максимум 1000 символов). Сократи и отправь снова.")
        return

    data = await state.get_data()
    photo_ids = data.get("prompt_gen_photo_ids", [])
    if not photo_ids:
        await state.clear()
        await message.answer("⚠️ Фото не найдено. Начни сначала — нажми «Генерация по промту».", reply_markup=get_main_menu_keyboard())
        return

    await state.clear()
    await analytics.track("prompt_generation_submitted", user_id=str(message.from_user.id), properties={"prompt_length": len(prompt), "photo_count": len(photo_ids)})

    await _do_prompt_generation(message, prompt, photo_ids=photo_ids, analytics=analytics)


async def _do_prompt_generation(
    message: Message, prompt: str, photo_ids: list[int],
    telegram_id: int | None = None, analytics: AnalyticsClient | None = None,
):
    """Start prompt generation → poll → send result."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("✨ Обрабатываю запрос и генерирую фото, подожди немного...")

    try:
        gen_result = await backend.generate_prompt(telegram_id=telegram_id, prompt=prompt, photo_ids=photo_ids)
    except Exception as e:
        logger.error(f"Ошибка запуска генерации по промту: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        if analytics:
            await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "no_balance_prompt_gen"})
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
        logger.info(f"[tg={telegram_id}] prompt_gen: скачиваю фото, url={url[:120]}")
        try:
            photo_data = await download_photo(url)
        except Exception as e:
            logger.error(f"[tg={telegram_id}] prompt_gen: download failed: {e}", exc_info=True)
            await message.answer("Не удалось скачать фото. Попробуй позже.")
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] prompt_gen: refund failed: {re}", exc_info=True)
            return

        logger.info(f"[tg={telegram_id}] prompt_gen: скачано {len(photo_data)} байт, отправляю в Telegram")
        send_result = await send_photos(message, [photo_data], telegram_id)

        if analytics:
            await analytics.track("prompt_generation_delivered", user_id=str(telegram_id), properties={"task_id": task_id, "success": send_result.failed == 0})

        if send_result.failed > 0:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] prompt_gen: refund failed: {re}", exc_info=True)

        total_time = time.monotonic() - t_total
        logger.info(f"[tg={telegram_id}] Prompt generation total={total_time:.2f}s")

        await message.answer(
            "✨ Готово! Хочешь ещё — нажми «Генерация по промту» снова.",
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
                logger.info(f"[tg={telegram_id}] prompt_gen: refunded 2 generations for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] prompt_gen: timeout refund failed: {refund_err}", exc_info=True)
