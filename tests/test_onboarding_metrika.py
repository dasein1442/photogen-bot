from app.handlers.onboarding import _parse_direct_bot_deep_link, _parse_metrika_deep_link
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


def test_parse_direct_bot_deep_link():
    assert _parse_direct_bot_deep_link("ydb_abcDEF12_token") == "ydb_abcDEF12_token"


def test_parse_invalid_direct_bot_deep_link():
    assert _parse_direct_bot_deep_link("ydb_bad!") is None


def test_build_offline_conversion_csv_for_client_id():
    csv_bytes = YandexMetrikaClient.build_offline_conversion_csv(
        identifier_name="ClientId",
        identifier_value="1773949959590379639",
        target="bot_started",
        timestamp=1775228394,
    )
    assert csv_bytes.decode("utf-8") == (
        "ClientId,Target,DateTime\n"
        "1773949959590379639,bot_started,1775228394\n"
    )


def test_build_offline_conversion_csv_for_yclid():
    csv_bytes = YandexMetrikaClient.build_offline_conversion_csv(
        identifier_name="Yclid",
        identifier_value="987654321",
        target="bot_started",
        timestamp=1775228394,
    )
    assert csv_bytes.decode("utf-8") == (
        "Yclid,Target,DateTime\n"
        "987654321,bot_started,1775228394\n"
    )
