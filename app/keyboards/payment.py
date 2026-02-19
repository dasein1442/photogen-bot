from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_payment_offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти к оплате 💜", callback_data="go_payment")],
        ]
    )


def get_payment_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить СПБ", callback_data="pay_spb")],
            [InlineKeyboardButton(text="Оплатить звёздами ⭐️", callback_data="pay_stars")],
        ]
    )
