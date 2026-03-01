from aiogram.fsm.state import State, StatesGroup


class PhotoUploadStates(StatesGroup):
    waiting_for_main_photo = State()
    onboarding_paywall = State()
