from app.handlers.onboarding import _parse_metrika_deep_link
from app.services.yandex_metrika import YandexMetrikaClient


def test_parse_regular_deep_link_without_metrika_payload():
    assert _parse_metrika_deep_link("landing") == ("landing", None)


def test_parse_metrika_deep_link():
    assert _parse_metrika_deep_link("yd_landing_1773949959590379639") == (
        "landing",
        "1773949959590379639",
    )


def test_parse_metrika_deep_link_with_underscored_source():
    assert _parse_metrika_deep_link("yd_campaign_test_1773949959590379639") == (
        "campaign_test",
        "1773949959590379639",
    )


def test_parse_malformed_metrika_payload_falls_back_to_landing():
    assert _parse_metrika_deep_link("yd_landing_not-a-client-id") == ("landing", None)


def test_build_offline_conversion_csv():
    csv_bytes = YandexMetrikaClient.build_offline_conversion_csv(
        client_id="1773949959590379639",
        target="bot_started",
        timestamp=1775228394,
    )
    assert csv_bytes.decode("utf-8") == (
        "ClientId,Target,DateTime\n"
        "1773949959590379639,bot_started,1775228394\n"
    )
