import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_buy_keyboard
from app.handlers.generation import _format_validation_errors, _do_generation
from app.services.tg_sender import download_photo, send_photos
from app.handlers.random_photo import _do_random_generation

logger = logging.getLogger(__name__)
router = Router()

WELCOME_PRICE_IMAGE_PATH = Path(__file__).resolve().parents[1] / "assets" / "welcome_price.jpg"


async def _handle_upload(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Загрузка фото, установка как profile photo, авто-генерация если пришли из flow."""
    await message.answer("🔄 Проверяю фотографию...")

    photo = message.photo[-1]

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

    # Определяем источник загрузки (до валидации, чтобы трекать все попытки)
    data = await state.get_data()
    photosession_id = data.get("photosession_id")
    random_mode = data.get("random_mode", False)
    onboarding_mode = data.get("onboarding_mode", False)

    if onboarding_mode:
        upload_source = "onboarding"
    elif random_mode:
        upload_source = "random"
    elif photosession_id:
        upload_source = "photosession"
    else:
        upload_source = "profile"

    await analytics.track("photo_upload_started", user_id=str(message.from_user.id), properties={"source": upload_source})

    # Загружаем на бэкенд (с валидацией)
    try:
        result = await backend.upload_photo(
            telegram_id=message.from_user.id,
            photo_bytes=photo_data,
            filename=f"{message.from_user.id}_{photo.file_id}.jpg",
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото на бэкенд: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось связаться с сервером. Попробуй позже.")
        return

    if not result.get("ok"):
        errors = result.get("errors", [])
        await message.answer(_format_validation_errors(errors))
        return  # пользователь остаётся в том же состоянии, может отправить ещё

    # Устанавливаем как profile photo
    photo_id = result.get("photo_id")
    try:
        await backend.set_profile_photo(
            telegram_id=message.from_user.id,
            photo_id=photo_id,
        )
    except Exception as e:
        logger.error(f"Ошибка установки profile photo: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось сохранить фото профиля. Попробуй позже.")
        return

    await state.clear()

    if onboarding_mode:
        # Пришли из онбординга — запускаем генерацию по онбординговому пресету
        await _do_onboarding_generation(message, state=state, analytics=analytics)
    elif random_mode:
        # Пришли из flow случайной генерации
        await _do_random_generation(message, analytics=analytics)
    elif photosession_id:
        # Пришли из flow генерации — запускаем генерацию автоматически
        await _do_generation(message, photosession_id, analytics=analytics)
    else:
        # Пришли из профиля — просто сообщаем об успехе
        await message.answer(
            "Готово ✅\n\n"
            "Бот обработал твои фотографии, и теперь ты можешь создавать "
            "снимки с собой в любом образе и месте.\n\n"
            "Попробуй свой первый запрос прямо сейчас, выбирай любой доступный "
            "инструмент, и генерируй шикарные фотографии 👇",
            reply_markup=get_main_menu_keyboard(),
        )


async def _do_onboarding_generation(message: Message, state: FSMContext | None = None, telegram_id: int | None = None, analytics: AnalyticsClient | None = None):
    """Онбординговая генерация по фиксированному пресету → поллинг → отправка результата → пейволл."""
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("⏳ Создаю твоё первое фото, подожди немного...")

    try:
        gen_result = await backend.generate_onboarding_photo(telegram_id=telegram_id)
    except Exception as e:
        logger.error(f"Ошибка запуска онбординговой генерации: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        await message.answer(
            "❌ У тебя закончились генерации!\n\n"
            "Пополни баланс, чтобы продолжить создавать фото.",
            reply_markup=get_buy_keyboard(),
        )
        return

    if gen_result.get("error") == "no_presets":
        await message.answer(
            "😔 Пока нет доступных образов. Попробуй позже.",
            reply_markup=get_main_menu_keyboard(),
        )
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
        logger.info(f"[tg={telegram_id}] onboarding: скачиваю фото, url={url[:120]}")
        try:
            photo_data = await download_photo(url)
        except Exception as e:
            logger.error(f"[tg={telegram_id}] onboarding: download failed: {e}", exc_info=True)
            await message.answer("Не удалось скачать фото. Попробуй позже.")
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] onboarding: refund failed: {re}", exc_info=True)
            return

        logger.info(f"[tg={telegram_id}] onboarding: скачано {len(photo_data)} байт, отправляю в Telegram")
        send_result = await send_photos(message, [photo_data], telegram_id)

        if analytics:
            await analytics.track("onboarding_result_delivered", user_id=str(telegram_id), properties={"task_id": task_id})

        # Mark onboarding completed and start paywall nudge notifications
        try:
            await backend.notify_onboarding_paywall(telegram_id)
        except Exception as e:
            logger.error(f"Failed to mark onboarding completed: {e}")

        if send_result.failed > 0:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] onboarding: refund failed: {re}", exc_info=True)

        # Show result message with like/dislike feedback buttons
        await message.answer(
            "😍 Смотри, какая ты получилась!\n\n"
            "Это только проба — дальше будет ещё круче!\n\n"
            "Как тебе результат?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="👍 Нравится", callback_data="onboarding_feedback:like"),
                    InlineKeyboardButton(text="👎 Не нравится", callback_data="onboarding_feedback:dislike"),
                ],
            ]),
        )

    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
        if task_id:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=1)
                logger.info(f"[tg={telegram_id}] onboarding: refunded 1 generation for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] onboarding: timeout refund failed: {refund_err}", exc_info=True)


@router.message(F.photo, PhotoUploadStates.waiting_for_main_photo)
async def handle_main_photo_upload(message: Message, state: FSMContext, analytics: AnalyticsClient):
    await _handle_upload(message, state, analytics)


@router.callback_query(lambda callback: callback.data == "upload_profile_photo")
async def handle_upload_profile_photo(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()

    await state.set_state(PhotoUploadStates.waiting_for_main_photo)

    photo_instructions_text = (
        "Отправьте фотографию в чат!\n\n"
        "После этого нейросеть проведет модерацию фотографии. Это займет 5 секунд. "
        "Это нужно, чтобы убедиться, что ты соблюдаешь все условия ниже, "
        "ведь плохая фотография = плохие генерации!\n\n"
        "**Несколько важных моментов к фото:**\n"
        "• Используй крупный план (лучше селфи).\n"
        "• Без других людей и животных.\n"
        "• Лицо нейтральное или с лёгкой улыбкой.\n"
        "• Голова прямо, без наклонов.\n"
        "• Без очков и аксессуаров на лице.\n"
        "• Хорошее освещение — залог качественного результата."
    )

    await callback.message.answer(
        photo_instructions_text,
        parse_mode="Markdown",
    )

    await callback.answer()


DISLIKE_REASONS = [
    ("😕 Лицо не похоже на моё", "face_mismatch"),
    ("🤖 Выглядит неестественно", "unnatural"),
    ("🎨 Не нравится стиль / образ", "style_dislike"),
]


@router.callback_query(lambda callback: callback.data and callback.data.startswith("onboarding_feedback:"))
async def handle_onboarding_feedback(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Save like/dislike feedback on onboarding photo.
    Like → proceed to paywall.
    Dislike → save immediately, then show reason buttons.
    """
    feedback = callback.data.split(":")[1]  # "like" or "dislike"
    telegram_id = callback.from_user.id

    # Save feedback immediately (before showing reason buttons for dislike)
    try:
        await backend.save_onboarding_photo_feedback(telegram_id, feedback)
    except Exception as e:
        logger.error(f"Failed to save onboarding feedback: {e}")

    await analytics.track("onboarding_photo_feedback", user_id=str(telegram_id), properties={"feedback": feedback})

    if feedback == "like":
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👍 Нравится ✓", callback_data="noop")],
            ]),
        )
        await _show_onboarding_paywall(callback, analytics)
    else:
        # Dislike — update button and show reason selection
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👎 Не нравится ✓", callback_data="noop")],
            ]),
        )
        reason_buttons = [
            [InlineKeyboardButton(text=label, callback_data=f"onboarding_dislike_reason:{value}")]
            for label, value in DISLIKE_REASONS
        ]
        await callback.message.answer(
            "Что именно не понравилось?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=reason_buttons),
        )

    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("onboarding_dislike_reason:"))
async def handle_onboarding_dislike_reason(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Save dislike reason, then proceed to paywall."""
    reason = callback.data.split(":")[1]  # "face_mismatch", "unnatural", "style_dislike"
    telegram_id = callback.from_user.id

    try:
        await backend.save_onboarding_feedback_reason(telegram_id, reason)
    except Exception as e:
        logger.error(f"Failed to save onboarding dislike reason: {e}")

    await analytics.track(
        "onboarding_dislike_reason",
        user_id=str(telegram_id),
        properties={"reason": reason},
    )

    # Collapse reason buttons to show selected choice
    label = next((label for label, value in DISLIKE_REASONS if value == reason), reason)
    selected_text = f"{label} ✓"

    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=selected_text, callback_data="noop")],
        ]),
    )

    await _show_onboarding_paywall(callback, analytics)
    await callback.answer()


async def _show_onboarding_paywall(callback: CallbackQuery, analytics: AnalyticsClient):
    """Show welcome_price promo image with discount text and payment button."""
    await analytics.track("onboarding_next_clicked", user_id=str(callback.from_user.id))

    promo_text = (
        "🔥 Скидка 70% только первый час!\n"
        "Полный доступ за 389₽ вместо 1500₽\n\n"
        "Получи не просто пробу, а весь функционал навсегда 👇\n\n"
        "– 80+ готовых образов\n"
        "– Более 15 фотосессий в разных стилях\n\n"
        "✨ Всё это по цене дешевле кофе с круассаном ☕️🥐\n"
        "Но результат останется навсегда — как твои лучшие фото.\n\n"
        "Акция действует только 1 час ⏳\n"
        "Не упусти шанс активировать доступ по сниженной цене."
    )

    payment_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти к оплате 💜", callback_data="onboarding_pay")],
    ])

    if WELCOME_PRICE_IMAGE_PATH.exists():
        await callback.message.answer_photo(
            photo=FSInputFile(str(WELCOME_PRICE_IMAGE_PATH)),
            caption=promo_text,
            reply_markup=payment_keyboard,
        )
    else:
        await callback.message.answer(
            promo_text,
            reply_markup=payment_keyboard,
        )


@router.callback_query(lambda callback: callback.data == "onboarding_next")
async def handle_onboarding_next(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Legacy handler for old 'Перейти дальше' button — redirects to paywall."""
    await _show_onboarding_paywall(callback, analytics)
    await callback.answer()


@router.callback_query(lambda callback: callback.data == "onboarding_pay")
async def handle_onboarding_pay(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Go directly to payment from the onboarding promo."""
    await analytics.track("onboarding_pay_clicked", user_id=str(callback.from_user.id))

    from app.handlers.payment import start_onboarding_payment
    await start_onboarding_payment(callback.message, callback.from_user.id, state, analytics)
    await callback.answer()
