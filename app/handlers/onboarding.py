from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto

from app.api.backend import backend
from app.keyboards.onboarding import get_welcome_keyboard, get_more_examples_keyboard, get_next_step_keyboard
from app.keyboards.common import get_main_menu_keyboard

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


@router.message(CommandStart())
async def handle_start(message: Message):
    user = message.from_user

    await backend.create_user(
        telegram_id=user.id,
        username=user.username,
    )

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
async def handle_more_examples(callback: CallbackQuery):
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
async def handle_try_now(callback: CallbackQuery):
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
    
    await callback.answer()
