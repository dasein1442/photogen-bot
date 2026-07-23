from app.handlers.onboarding import PAYMENT_PUSH_OFFERS, PHOTOSESSIONS_PUSH_SLUGS


def test_active_paywall_pushes_keep_their_advertised_offers():
    assert PAYMENT_PUSH_OFFERS["onboarding_paywall_reminder_1"] == {
        "generations": 20,
        "rubles": 289,
        "source": "onboarding_paywall_reminder_1",
    }
    assert PAYMENT_PUSH_OFFERS["onboarding_paywall_reminder_2"] == {
        "generations": 20,
        "rubles": 249,
        "source": "onboarding_paywall_reminder_2",
    }


def test_every_active_regular_push_opens_photosessions():
    assert PHOTOSESSIONS_PUSH_SLUGS == {
        "weekly_monday",
        "daily_thursday",
        "daily_friday",
        "daily_saturday",
        "daily_sunday",
    }
