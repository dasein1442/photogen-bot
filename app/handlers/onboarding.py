import logging
from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto, LabeledPrice

from app.api.backend import backend
from app.handlers.payment import start_payment_flow
from app.keyboards.onboarding import get_welcome_keyboard, get_more_examples_keyboard
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


async def _send_onboarding_paywall(message: Message, telegram_id: int, state: FSMContext):
    """Show paywall for user who completed onboarding but hasn't purchased. Shows price + invoice."""
    try:
        price_data = await backend.get_price(telegram_id, context="onboarding_paywall")
        tier = price_data["tiers"][0]
        stars = tier["stars"]
        generations = tier["generations"]
    except Exception:
        stars = 299
        generations = 20

    await message.answer(
        f"Открой доступ к 70+ стилям — {generations} генераций всего за {stars} ⭐️\n\n"
        "Деловая съёмка, пляж, Pinterest, Vogue и многое другое 👇"
    )

    await message.bot.send_invoice(
        chat_id=message.chat.id,
        title=f"{generations} генераций",
        description=f"Покупка {generations} генераций для создания AI-фото",
        payload=f"buy_{generations}_{telegram_id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{generations} генераций", amount=stars)],
    )

    await state.set_state(PhotoUploadStates.onboarding_paywall)


@router.message(CommandStart(deep_link="upload_photo"))
async def handle_start_upload_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Deep link from onboarding reminder push — go straight to photo upload."""
    user = message.from_user

    # Регистрация (idempotent)
    result = {}
    try:
        result = await backend.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user.id}: {e}")

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={"deep_link": "upload_photo", "is_new_user": result.get("created", True)})

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
        "Отправь 1 фото — я сделаю тебе тестовый снимок за несколько секунд 🤖✨\n\n"
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

    # Регистрация (idempotent)
    result = {}
    try:
        result = await backend.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user.id}: {e}")

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={"deep_link": "buy", "is_new_user": result.get("created", True)})

    # Check if user is in post-onboarding paywall scenario
    try:
        user_data = await backend.get_user(telegram_id=user.id)
        user_info = user_data.get("user", {})
        if user_info.get("onboarding_completed") and not user_info.get("has_purchased"):
            await _send_onboarding_paywall(message, user.id, state)
            return
    except Exception:
        pass

    await start_payment_flow(message, user.id, analytics=analytics)


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext, analytics: AnalyticsClient):
    user = message.from_user

    # Регистрация пользователя на бэкенде
    reg_data = {}
    try:
        reg_data = await backend.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        generations = reg_data.get("generations_remaining", "?")
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user.id}: {e}")
        generations = "?"

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={"deep_link": "none", "is_new_user": reg_data.get("created", True)})

    # Check if user completed onboarding but hasn't purchased — show paywall
    try:
        user_data = await backend.get_user(telegram_id=user.id)
        user_info = user_data.get("user", {})
        if user_info.get("onboarding_completed") and not user_info.get("has_purchased"):
            await _send_onboarding_paywall(message, user.id, state)
            return
    except Exception:
        pass

    welcome_text = (
        "Привет 👋\n"
        "Ты в Фотушке — боте, который делает из твоих обычных фото новые профессиональные снимки с помощью ИИ 🤖✨\n\n"
        "Загрузи несколько своих селфи — и нейросеть создаст тебя:\n"
        "в фотосессии на яхте, в деловом образе, на обложке журнала или даже в стиле Pinterest 💅\n\n"
        "Что умеет Фотушка:\n"
        "📸 Более 70 стильных образов\n"
        "🪄 Генерация фото по твоему описанию\n"
        "🌅 50+ продуманных фотосетов с разной атмосферой\n\n"
        "Попробуй прямо сейчас — это займёт минуту!"
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
        )
        return

    await message.answer(
        welcome_text,
        reply_markup=get_welcome_keyboard(),
    )


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
