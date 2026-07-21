from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📸 Создать фотосессию")],
            [KeyboardButton(text="🎬 Оживить фото")],
            [KeyboardButton(text="💫 Новый образ"), KeyboardButton(text="✨ Изменить фото")],
            [KeyboardButton(text="🔍 Улучшить кач-во")],
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Служба заботы")],
        ],
        resize_keyboard=True
    )


def get_profile_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Приобрести генерации")],
            [KeyboardButton(text="Установить женское фото")],
            [KeyboardButton(text="Установить мужское фото")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True
    )
