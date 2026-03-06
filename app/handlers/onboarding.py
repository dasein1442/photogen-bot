import logging
from datetime import timedelta
from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto

from app.api.backend import backend
from app.keyboards.onboarding import get_welcome_keyboard, get_more_examples_keyboard
from app.keyboards.payment import get_payment_method_keyboard
from app.services.analytics_sdk import AnalyticsClient
from app.states.photo import PhotoUploadStates

logger = logging.getLogger(__name__)
router = Router()

WELCOME_PROMO_IMAGE_DIR = Path(__file__).resolve().parents[1] / "assets"
WELCOME_PROMO_IMAGE_CANDIDATES = (
    "welcome_promo.png",
    "welcome_promo.jpg",
    "welcome_promo.jpeg",
    "welcome_promo.png.jpg",
)
TRY_NOW_IMAGE_PATH = WELCOME_PROMO_IMAGE_DIR / "welocme_one_generation.jpg"
WELCOME_EXAMPLE_IMAGE_PATHS = (
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_1.jpg",
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_2.jpg",
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_3.jpg",
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_4.jpg",
)


async def _show_welcome(message: Message):
    """Show the welcome message with promo image."""
    welcome_text = (
        "<b>Привет</b> 👋\n\n"
        "Ты в <b>Кадрице</b> — боте, который делает из твоего фото профессиональные снимки с помощью ИИ ✨\n\n"
        "Загрузи одно селфи — и нейросеть создаст <b>реалистичные фотосессии</b>: на яхте, в деловом образе, на обложке журнала или даже в стиле селебрити 💅\n\n"
        "<b>Попробуй прямо сейчас — это займёт минуту!</b>"
    )

    promo_image_path = next(
        (WELCOME_PROMO_IMAGE_DIR / name for name in WELCOME_PROMO_IMAGE_CANDIDATES if (WELCOME_PROMO_IMAGE_DIR / name).exists()),
        None,
    )

    if promo_image_path:
        await message.answer_photo(
            photo=FSInputFile(str(promo_image_path)),
            caption=welcome_text,
            reply_markup=get_welcome_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            welcome_text,
            reply_markup=get_welcome_keyboard(),
            parse_mode="HTML",
        )


async def _send_onboarding_paywall(message: Message, telegram_id: int, state: FSMContext):
    """Show paywall for user who completed onboarding but hasn't purchased. Shows payment method selection."""
    await message.answer(
        "Открой доступ к 70+ стилям!\n\n"
        "Деловая съёмка, пляж, Pinterest, Vogue и многое другое.\n\n"
        "Выбери способ оплаты 👇",
        reply_markup=get_payment_method_keyboard("onboarding"),
    )

    await state.set_state(PhotoUploadStates.onboarding_paywall)


@router.message(CommandStart(deep_link="upload_photo"))
async def handle_start_upload_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Deep link from onboarding reminder push — go straight to photo upload."""
    user = message.from_user

    # Deduplicate rapid /start messages (Telegram client may send two)
    data = await state.get_data()
    last_start_date = data.get("_last_start_date")
    if last_start_date and (message.date - last_start_date) < timedelta(seconds=5):
        return
    await state.update_data(_last_start_date=message.date)

    # Регистрация (idempotent)
    result = {}
    try:
        result = await backend.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            source="upload_photo",
        )
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user.id}: {e}")

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={"deep_link": "upload_photo", "source": "upload_photo", "is_new_user": result.get("created", True)})

    # New user — show full welcome instead of jumping to upload
    if result.get("created", False):
        await state.clear()
        return await _show_welcome(message)

    # Check if user completed onboarding but hasn't purchased — show paywall
    try:
        user_data = await backend.get_user(telegram_id=user.id)
        user_info = user_data.get("user", {})
        if user_info.get("onboarding_completed") and not user_info.get("has_purchased"):
            await _send_onboarding_paywall(message, user.id, state)
            return
    except Exception:
        pass

    try_now_text = (
        "🔥 Давай посмотрим, как ты выглядишь в AI-версии!\n\n"
        "Отправь 1 фото — я сделаю тебе тестовый снимок за несколько секунд ✨\n\n"
        "💡 Лучше обычное селфи с хорошим светом — без фильтров и других людей.\n\n"
        "🔒 Фото обрабатывается только нейросетью и не сохраняется — всё полностью приватно."
    )

    if TRY_NOW_IMAGE_PATH.exists():
        await message.answer_photo(
            photo=FSInputFile(str(TRY_NOW_IMAGE_PATH)),
            caption=try_now_text,
        )
    else:
        await message.answer(try_now_text)

    await state.set_state(PhotoUploadStates.waiting_for_main_photo)
    await state.update_data(onboarding_mode=True)


@router.message(CommandStart(deep_link="buy"))
async def handle_start_buy(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Deep link from payment reminder push — go straight to Stars invoice."""
    user = message.from_user

    # Deduplicate rapid /start messages (Telegram client may send two)
    data = await state.get_data()
    last_start_date = data.get("_last_start_date")
    if last_start_date and (message.date - last_start_date) < timedelta(seconds=5):
        return
    await state.update_data(_last_start_date=message.date)

    # Регистрация (idempotent)
    result = {}
    try:
        result = await backend.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            source="buy",
        )
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user.id}: {e}")

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={"deep_link": "buy", "source": "buy", "is_new_user": result.get("created", True)})

    # Check if user is in post-onboarding paywall scenario
    try:
        user_data = await backend.get_user(telegram_id=user.id)
        user_info = user_data.get("user", {})
        if user_info.get("onboarding_completed") and not user_info.get("has_purchased"):
            await _send_onboarding_paywall(message, user.id, state)
            return
    except Exception:
        pass

    await message.answer(
        "Выбери способ оплаты 👇",
        reply_markup=get_payment_method_keyboard("menu"),
    )


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext, analytics: AnalyticsClient):
    user = message.from_user

    # Deduplicate rapid /start messages (Telegram client may send two)
    data = await state.get_data()
    last_start_date = data.get("_last_start_date")
    if last_start_date and (message.date - last_start_date) < timedelta(seconds=5):
        logger.info(f"handle_start SKIPPED (dedup): user={user.id}")
        return
    await state.update_data(_last_start_date=message.date)

    # Извлекаем deep_link параметр из текста команды (формат: "/start yd1")
    parts = (message.text or "").split(maxsplit=1)
    deep_link_param = parts[1] if len(parts) > 1 else None
    source = deep_link_param if deep_link_param not in (None, "upload_photo", "buy") else None

    # Регистрация пользователя на бэкенде
    reg_data = {}
    try:
        reg_data = await backend.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            source=source,
        )
        generations = reg_data.get("generations_remaining", "?")
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user.id}: {e}")
        generations = "?"

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={"deep_link": deep_link_param or "none", "source": source, "is_new_user": reg_data.get("created", True)})

    # Clear any stale FSM state (e.g. onboarding_paywall) so buttons work
    await state.clear()

    # Check if user completed onboarding but hasn't purchased — show paywall
    try:
        user_data = await backend.get_user(telegram_id=user.id)
        user_info = user_data.get("user", {})
        if user_info.get("onboarding_completed") and not user_info.get("has_purchased"):
            await _send_onboarding_paywall(message, user.id, state)
            return
    except Exception:
        pass

    await _show_welcome(message)


@router.callback_query(lambda callback: callback.data == "more_examples")
async def handle_more_examples(callback: CallbackQuery, analytics: AnalyticsClient):
    await analytics.track("examples_viewed", user_id=str(callback.from_user.id))
    await callback.message.delete()

    existing_example_images = [path for path in WELCOME_EXAMPLE_IMAGE_PATHS if path.exists()]

    if existing_example_images:
        await callback.message.answer_media_group(
            media=[InputMediaPhoto(media=FSInputFile(str(path))) for path in existing_example_images],
        )

    await callback.message.answer(
        "Вау, посмотри на эти кадры 🤯\n"
        "Первое фото — настоящее, а всё остальное создала нейросеть!\n\n"
        "Представь, как твои соцсети будут выглядеть с такими снимками 😎\n"
        "Реалистично, стильно и с вайбом настоящей фотосессии.\n\n"
        "Хочешь такие же?\n"
        "👉 Попробуй прямо сейчас — загрузить свои фото",
        reply_markup=get_more_examples_keyboard()
    )

    await callback.answer()


@router.callback_query(lambda callback: callback.data == "try_now")
async def handle_try_now(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    await analytics.track("onboarding_try_now_clicked", user_id=str(callback.from_user.id))
    try_now_text = (
        "🔥 Давай посмотрим, как ты выглядишь в AI-версии!\n\n"
        "Отправь 1 фото — я сделаю тебе тестовый снимок за несколько секунд 🤖✨\n\n"
        "💡 Лучше обычное селфи с хорошим светом — без фильтров и других людей.\n\n"
        "🔒 Фото обрабатывается только нейросетью и не сохраняется — всё полностью приватно."
    )

    if TRY_NOW_IMAGE_PATH.exists():
        await callback.message.answer_photo(
            photo=FSInputFile(str(TRY_NOW_IMAGE_PATH)),
            caption=try_now_text,
        )
    else:
        await callback.message.answer(
            try_now_text,
        )

    await state.set_state(PhotoUploadStates.waiting_for_main_photo)
    await state.update_data(onboarding_mode=True)

    await callback.answer()
