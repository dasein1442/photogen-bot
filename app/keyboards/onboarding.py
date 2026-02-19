from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Попробовать ✅", callback_data="try_now")],
            [InlineKeyboardButton(text="Больше примеров", callback_data="more_examples")]
        ]
    )


def get_more_examples_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Попробовать ✅", callback_data="try_now")],
        ]
    )


def get_next_step_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти дальше 🚀", callback_data="go_next")],
        ]
    )
