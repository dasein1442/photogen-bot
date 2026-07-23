from aiogram import Router

from . import animate_photo, custom_prompt, generation, menu, onboarding, payment, photo_upload, photosessions, profile, prompt_generation, random_photo, upscale


def get_all_routers() -> list[Router]:
    return [
        onboarding.router,
        photo_upload.router,
        random_photo.router,
        custom_prompt.router,
        prompt_generation.router,
        upscale.router,
        animate_photo.router,
        payment.router,
        profile.router,

        photosessions.router,
        menu.router,
        generation.router,
    ]
