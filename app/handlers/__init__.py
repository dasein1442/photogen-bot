from aiogram import Router

from . import onboarding, photo_upload, generation, payment, profile, menu, gallery, photosessions, random_photo


def get_all_routers() -> list[Router]:
    return [
        onboarding.router,
        photo_upload.router,
        random_photo.router,
        payment.router,
        profile.router,
        gallery.router,
        photosessions.router,
        menu.router,
        generation.router,
    ]
