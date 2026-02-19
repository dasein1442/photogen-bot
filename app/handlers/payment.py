from pathlib import Path

from aiogram import Router
from aiogram.types import CallbackQuery, FSInputFile

from app.keyboards.payment import get_payment_offer_keyboard, get_payment_method_keyboard
from app.keyboards.common import get_main_menu_keyboard

router = Router()

WELCOME_PROMO_IMAGE_DIR = Path(__file__).resolve().parents[1] / "assets"
WELCOME_PRICE_IMAGE_PATH = WELCOME_PROMO_IMAGE_DIR / "welcome_price.jpg"


@router.callback_query(lambda callback: callback.data == "go_next")
async def handle_go_next(callback: CallbackQuery):
    await callback.message.delete()

    price_text = (
        "🔥 Скидка 70% только первый час!\n"
        "Полный доступ за 398₽ вместо 1500₽\n\n"
        "Получи не просто пробу, а весь функционал навсегда 👇\n\n"
        "– 70+ готовых образов\n"
        "– Более 30 фотосессий в разных стилях\n"
        "– Возможность создавать фото по своему тексту\n"
        "– Улучшение и ретушь своих снимков\n"
        "– Создание фото 'по примеру': загрузи картинку из Pinterest — получи такую же, но с собой\n\n"
        "✨ Всё это по цене дешевле кофе с круассаном ☕🥐\n"
        "Но результат останется навсегда — как твои лучшие фото.\n\n"
        "Акция действует только 1 час ⏳\n"
        "Не упусти шанс активировать доступ по сниженной цене."
    )

    if WELCOME_PRICE_IMAGE_PATH.exists():
        await callback.message.answer_photo(
            photo=FSInputFile(str(WELCOME_PRICE_IMAGE_PATH)),
            caption=price_text,
            reply_markup=get_payment_offer_keyboard(),
        )
    else:
        await callback.message.answer(
            price_text,
            reply_markup=get_payment_offer_keyboard(),
        )

    await callback.answer()


@router.callback_query(lambda callback: callback.data == "go_payment")
async def handle_go_payment(callback: CallbackQuery):
    await callback.message.delete()

    payment_text = (
        "Оплата 398₽\n\n"
        "Вы оплачиваете: «Доступ в бота и 20 генераций». "
        "Мы не имеем доступа к вашим личным и платежным данным. "
        "Переходя к оплате, вы подтверждаете ознакомление и согласие с нашим "
        "пользовательским соглашением (https://fotushka.com/pol) и политикой конфиденциальности (https://fotushka.com/pol).\n\n"
        "Генерации - валюта нашего сервиса.\n"
        "1 сгенерированное фото = 1 генерация.\n\n"
        "В случае возникновения проблем обращайтесь в чат поддержки (https://t.me/fotushkasupport)."
    )

    await callback.message.answer(
        payment_text,
        reply_markup=get_payment_method_keyboard(),
    )

    await callback.answer()


@router.callback_query(lambda callback: callback.data == "pay_spb")
async def handle_pay_spb(callback: CallbackQuery):
    await callback.message.delete()

    await callback.message.answer(
        "Спасибо за поддержку оплатой ❤️",
        reply_markup=get_main_menu_keyboard(),
    )

    await callback.answer()


@router.callback_query(lambda callback: callback.data == "pay_stars")
async def handle_pay_stars(callback: CallbackQuery):
    await callback.message.delete()

    await callback.message.answer(
        "Спасибо за поддержку оплатой ❤️",
        reply_markup=get_main_menu_keyboard(),
    )

    await callback.answer()
