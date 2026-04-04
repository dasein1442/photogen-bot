import os
from dotenv import load_dotenv

load_dotenv()

# Токен Telegram-бота (обязательно)
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# URL бэкенда photogen
BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")

# Секретный токен для авторизации запросов к бэкенду
API_SECRET_TOKEN: str = os.getenv("API_SECRET_TOKEN", "")


# Аналитика
ANALYTICS_URL: str = os.getenv("ANALYTICS_URL", "http://94.198.219.69:8100")
ANALYTICS_API_KEY: str = os.getenv("ANALYTICS_API_KEY", "579f0cf8-b7c8-4665-b1c3-c8bcf3b14e25")
ANALYTICS_ENABLED: bool = os.getenv("ANALYTICS_ENABLED", "true").lower() == "true"

# Yandex Metrika offline conversions
YANDEX_METRIKA_ENABLED: bool = os.getenv("YANDEX_METRIKA_ENABLED", "true").lower() == "true"
YANDEX_METRIKA_OAUTH_TOKEN: str = os.getenv("YANDEX_METRIKA_OAUTH_TOKEN", "")
YANDEX_METRIKA_COUNTER_ID: str = os.getenv("YANDEX_METRIKA_COUNTER_ID", "108158643")
YANDEX_METRIKA_GOAL: str = os.getenv("YANDEX_METRIKA_GOAL", "bot_started")


def validate():
    """Проверяет что все обязательные настройки заполнены."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан. Заполни .env файл.")
    if not API_SECRET_TOKEN:
        raise ValueError("API_SECRET_TOKEN не задан. Заполни .env файл.")
