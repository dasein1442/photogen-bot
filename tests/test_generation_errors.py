from app.services.generation_errors import CONTENT_MODERATION_MESSAGE, has_content_moderation_error


def test_detects_content_moderation_in_failed_result():
    task_result = {
        "status": "completed",
        "results": [{"status": "failed", "error_message": "content_moderation"}],
    }

    assert has_content_moderation_error(task_result) is True


def test_does_not_treat_regular_failure_as_moderation():
    task_result = {
        "status": "failed",
        "error_message": "RuntimeError: upstream timeout",
    }

    assert has_content_moderation_error(task_result) is False


def test_content_moderation_message_mentions_refund_and_retry():
    assert "вернулись на баланс" in CONTENT_MODERATION_MESSAGE
    assert "описать идею чуть мягче" in CONTENT_MODERATION_MESSAGE
