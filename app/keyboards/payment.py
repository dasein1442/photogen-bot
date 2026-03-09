from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить генерации 💳", callback_data="buy_generations")],
        ]
    )
