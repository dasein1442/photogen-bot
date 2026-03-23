import logging

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


@router.message(F.text == "Случайное фото")
async def handle_random_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Обработка кнопки 'Случайное фото'."""
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось получить данные. Попробуй позже.")
        return

    profile_photo_id = user_data.get("user", {}).get("profile_photo_id")

    if not profile_photo_id:
        await state.set_data({"random_mode": True})
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

    await _do_random_generation(message, analytics=analytics)


async def _do_random_generation(message: Message, telegram_id: int | None = None, analytics: AnalyticsClient | None = None):
    """Запуск случайной генерации → поллинг → отправка результата."""
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("🎲 Подбираю случайный образ, подожди немного...")

    try:
        gen_result = await backend.generate_random_photo(telegram_id=telegram_id)
    except Exception as e:
        logger.error(f"Ошибка запуска случайной генерации: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        if analytics:
            await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "no_balance_random"})
        await message.answer(
            "❌ У тебя закончились генерации!\n\n"
            "Пополни баланс, чтобы продолжить создавать фото.",
            reply_markup=get_buy_keyboard(),
        )
        return

    if gen_result.get("error") == "no_presets":
        await message.answer(
            "😔 Сейчас нет доступных образов для случайного фото. Попробуй позже.",
            reply_markup=get_main_menu_keyboard(),
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
        logger.info(f"[tg={telegram_id}] random: скачиваю фото, url={url[:120]}")
        try:
            photo_data = await download_photo(url)
        except Exception as e:
            logger.error(f"[tg={telegram_id}] random: download failed: {e}", exc_info=True)
            await message.answer("Не удалось скачать фото. Попробуй позже.")
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] random: refund failed: {re}", exc_info=True)
            return

        logger.info(f"[tg={telegram_id}] random: скачано {len(photo_data)} байт, отправляю в Telegram")
        send_result = await send_photos(message, [photo_data], telegram_id)

        if analytics:
            await analytics.track("random_generation_delivered", user_id=str(telegram_id), properties={"task_id": task_id, "success": send_result.failed == 0})

        if send_result.failed > 0:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] random: refund failed: {re}", exc_info=True)

        await message.answer(
            "🎲 Вот твоё случайное фото!\n\n"
            "Нажми ещё раз «Случайное фото» для нового образа 📸",
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
                logger.info(f"[tg={telegram_id}] random: refunded 1 generation for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] random: timeout refund failed: {refund_err}", exc_info=True)
