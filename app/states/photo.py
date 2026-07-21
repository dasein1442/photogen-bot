from aiogram.fsm.state import State, StatesGroup


class PhotoUploadStates(StatesGroup):
    waiting_for_main_photo = State()
    waiting_for_additional_photo = State()
    onboarding_paywall = State()
    waiting_for_custom_prompt = State()
    waiting_for_photoshop_photo = State()
    waiting_for_photoshop_photo_or_prompt = State()
    # Генерация по промту
    waiting_for_prompt_gen_photo = State()
    waiting_for_prompt_gen_text = State()
    # Апскейл
    waiting_for_upscale_photo = State()
    # Оживление фото
    waiting_for_animation_photo = State()
    waiting_for_animation_prompt = State()
