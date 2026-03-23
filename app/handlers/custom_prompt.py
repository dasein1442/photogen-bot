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


@router.message(F.text == "ИИ-фотошоп")
async def handle_custom_prompt_button(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь нажал 'ИИ-фотошоп' в главном меню."""
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось получить данные. Попробуй позже.")
        return

    profile_photo_id = user_data.get("user", {}).get("profile_photo_id")

    if not profile_photo_id:
        await state.set_data({"custom_prompt_mode": True})
        await state.set_state(PhotoUploadStates.waiting_for_main_photo)

        await message.answer(
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
        return

    await state.set_state(PhotoUploadStates.waiting_for_custom_prompt)

    await analytics.track("custom_prompt_opened", user_id=str(message.from_user.id))

    await message.answer(
        "🎨 Опиши, что хочешь изменить на фото — "
        "нейросеть сделает остальное.\n\n"
        "Например:\n"
        "• «Надень на меня чёрный костюм»\n"
        "• «Перенеси на пляж на закате»\n"
        "• «Сделай фото в стиле обложки Vogue»\n\n"
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

    await state.clear()
    await analytics.track("custom_prompt_submitted", user_id=str(message.from_user.id), properties={"prompt_length": len(prompt)})

    await _do_custom_prompt_generation(message, prompt, analytics=analytics)


async def _do_custom_prompt_generation(message: Message, prompt: str, telegram_id: int | None = None, analytics: AnalyticsClient | None = None):
    """Запуск генерации по кастомному промту → поллинг → отправка результата."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("✨ Генерирую фото по твоему промту, подожди немного...")

    # 1. Запуск генерации
    try:
        gen_result = await backend.generate_custom_prompt(telegram_id=telegram_id, prompt=prompt)
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
            "✨ Готово! Хочешь ещё — просто напиши новый промт или вернись в меню.",
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
