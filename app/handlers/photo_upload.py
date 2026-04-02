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
    onboarding_gender = data.get("onboarding_gender", "female")
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
        await message.answer("⚠️ Не удалось сохранить женское фото. Попробуй позже.")
        return

    await state.clear()

    if onboarding_mode:
        # Пришли из онбординга — запускаем генерацию по онбординговому пресету
        await _do_onboarding_generation(
            message,
            state=state,
            analytics=analytics,
            onboarding_gender=onboarding_gender,
        )
    elif random_mode:
        # Пришли из flow случайной генерации
        await _do_random_generation(message, analytics=analytics)
    elif photosession_id:
        # Пришли из flow генерации — запускаем генерацию автоматически
        await _do_generation(message, photosession_id, analytics=analytics)
    else:
        # Пришли из профиля — просто сообщаем об успехе
        await message.answer(
            "✅ Женское фото успешно установлено!\n\n"
            "Теперь ты можешь генерировать женские и парные фотосессии.",
            reply_markup=get_main_menu_keyboard(),
        )


async def _do_onboarding_generation(
    message: Message,
    state: FSMContext | None = None,
    telegram_id: int | None = None,
    analytics: AnalyticsClient | None = None,
    onboarding_gender: str | None = None,
):
    """Онбординговая генерация по фиксированному пресету → поллинг → отправка результата → пейволл."""
    if telegram_id is None:
        telegram_id = message.from_user.id

    if onboarding_gender is None:
        onboarding_gender = "female"
    if state is not None and onboarding_gender == "female":
        data = await state.get_data()
        onboarding_gender = data.get("onboarding_gender", "female")

    result_caption = "😍 Смотри, как круто ты получилась!" if onboarding_gender == "female" else "😍 Смотри, как круто ты получился!"

    await message.answer("⏳ Создаю твоё первое фото, подожди немного...")

    try:
        gen_result = await backend.generate_onboarding_photo(telegram_id=telegram_id, gender=onboarding_gender)
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
            f"{result_caption}\n\n"
            "Это только проба — дальше будет ещё круче!\n\n"
            "Как тебе результат?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="👍 Нравится", callback_data=f"photo_feedback:ob:{task_id}:like"),
                    InlineKeyboardButton(text="👎 Не нравится", callback_data=f"photo_feedback:ob:{task_id}:dislike"),
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


@router.message(F.photo, PhotoUploadStates.waiting_for_additional_photo)
async def handle_additional_photo_upload(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Загрузка дополнительного фото (фото партнёра)."""
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

    await analytics.track("additional_photo_upload_started", user_id=str(message.from_user.id))

    # Загружаем на бэкенд (с валидацией)
    try:
        result = await backend.upload_photo(
            telegram_id=message.from_user.id,
            photo_bytes=photo_data,
            filename=f"{message.from_user.id}_{photo.file_id}_additional.jpg",
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки доп. фото на бэкенд: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось связаться с сервером. Попробуй позже.")
        return

    if not result.get("ok"):
        errors = result.get("errors", [])
        await message.answer(_format_validation_errors(errors))
        return  # пользователь остаётся в том же состоянии, может отправить ещё

    # Устанавливаем как additional photo
    photo_id = result.get("photo_id")
    try:
        await backend.set_additional_photo(
            telegram_id=message.from_user.id,
            photo_id=photo_id,
        )
    except Exception as e:
        logger.error(f"Ошибка установки additional photo: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось сохранить мужское фото. Попробуй позже.")
        return

    data = await state.get_data()
    photosession_id = data.get("photosession_id")
    await state.clear()

    await analytics.track("additional_photo_uploaded", user_id=str(message.from_user.id))

    if photosession_id:
        # Пришли из flow генерации — запускаем генерацию автоматически
        await message.answer("✅ Мужское фото установлено!")
        await _do_generation(message, photosession_id, analytics=analytics)
    else:
        await message.answer(
            "✅ Мужское фото успешно установлено!\n\n"
            "Теперь ты можешь генерировать мужские и парные фотосессии.",
            reply_markup=get_main_menu_keyboard(),
        )


@router.callback_query(lambda callback: callback.data == "upload_additional_photo")
async def handle_upload_additional_photo_callback(callback: CallbackQuery, state: FSMContext):
    """Callback для загрузки фото партнёра (из inline-кнопки)."""
    try:
        await callback.message.delete()
    except Exception:
        pass

    data = await state.get_data()
    photosession_id = data.get("photosession_id")

    await state.set_state(PhotoUploadStates.waiting_for_additional_photo)
    if photosession_id:
        await state.update_data(photosession_id=photosession_id)

    await callback.message.answer(
        "📸 Загрузите фото вашего партнёра (мужчины)\n\n"
        "Это фото будет использоваться для мужских и парных фотосессий.\n\n"
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


@router.callback_query(lambda callback: callback.data and callback.data.startswith("photo_feedback:"))
async def handle_photo_feedback(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Save like/dislike feedback on a generation task.
    Callback data format: photo_feedback:{context}:{task_id}:{like|dislike}
    context: "ob" (onboarding) or "ps" (photoshoot)
    """
    parts = callback.data.split(":")
    context = parts[1]   # "ob" or "ps"
    task_id = int(parts[2])
    feedback = parts[3]  # "like" or "dislike"
    telegram_id = callback.from_user.id

    # Save feedback immediately (before showing reason buttons for dislike)
    try:
        await backend.save_photo_feedback(telegram_id, task_id, feedback)
    except Exception as e:
        logger.error(f"Failed to save photo feedback: {e}")

    await analytics.track(
        "photo_feedback",
        user_id=str(telegram_id),
        properties={"feedback": feedback, "generation_task_id": task_id, "context": context},
    )

    if feedback == "like":
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👍 Нравится ✓", callback_data="noop")],
            ]),
        )
        if context == "ob":
            await _show_onboarding_paywall(callback, analytics)
        else:
            await callback.message.answer(
                "Хочешь ещё? Выбери фотосессию в меню или отправь новое фото 📸",
                reply_markup=get_main_menu_keyboard(),
            )
    else:
        # Dislike — update button and show reason selection
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👎 Не нравится ✓", callback_data="noop")],
            ]),
        )
        reason_buttons = [
            [InlineKeyboardButton(text=label, callback_data=f"dislike_reason:{context}:{task_id}:{value}")]
            for label, value in DISLIKE_REASONS
        ]
        await callback.message.answer(
            "Что именно не понравилось?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=reason_buttons),
        )

    await callback.answer()


@router.callback_query(lambda callback: callback.data and callback.data.startswith("dislike_reason:"))
async def handle_dislike_reason(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Save dislike reason, then show paywall (onboarding) or menu (photoshoot).
    Callback data format: dislike_reason:{context}:{task_id}:{reason}
    """
    parts = callback.data.split(":")
    context = parts[1]   # "ob" or "ps"
    task_id = int(parts[2])
    reason = parts[3]    # "face_mismatch", "unnatural", "style_dislike"
    telegram_id = callback.from_user.id

    try:
        await backend.save_photo_feedback_reason(telegram_id, task_id, reason)
    except Exception as e:
        logger.error(f"Failed to save dislike reason: {e}")

    await analytics.track(
        "dislike_reason",
        user_id=str(telegram_id),
        properties={"reason": reason, "generation_task_id": task_id, "context": context},
    )

    # Collapse reason buttons to show selected choice
    label = next((label for label, value in DISLIKE_REASONS if value == reason), reason)
    selected_text = f"{label} ✓"

    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=selected_text, callback_data="noop")],
        ]),
    )

    if context == "ob":
        await _show_onboarding_paywall(callback, analytics)
    else:
        await callback.message.answer(
            "Спасибо за отзыв! Мы учтём это 🙏\n\n"
            "Хочешь попробовать другую фотосессию?",
            reply_markup=get_main_menu_keyboard(),
        )
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
