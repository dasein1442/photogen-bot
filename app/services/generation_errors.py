CONTENT_MODERATION_ERROR_CODE = "content_moderation"

CONTENT_MODERATION_MESSAGE = (
    "Ой, тут сработала цензура нейросети 🥺\n\n"
    "Прости, пожалуйста — я не смогла обработать этот запрос. Иногда фильтр слишком строго "
    "реагирует на откровенные образы.\n\n"
    "Попробуй описать идею чуть мягче — генерации уже вернулись на баланс 💛"
)


def has_content_moderation_error(task_result: dict) -> bool:
    """Check both task-level and per-result errors returned by the backend."""
    errors = [task_result.get("error_message")]
    errors.extend(result.get("error_message") for result in task_result.get("results") or [])
    return any(
        CONTENT_MODERATION_ERROR_CODE in str(error).casefold()
        for error in errors
        if error
    )
