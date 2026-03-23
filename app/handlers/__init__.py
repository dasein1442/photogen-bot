from aiogram import Router

from . import onboarding, photo_upload, generation, payment, profile, menu, photosessions, random_photo, custom_prompt


def get_all_routers() -> list[Router]:
    return [
        onboarding.router,
        photo_upload.router,
        random_photo.router,
        custom_prompt.router,
        payment.router,
        profile.router,

        photosessions.router,
        menu.router,
        generation.router,
    ]
