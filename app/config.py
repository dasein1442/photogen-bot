import os
from dotenv import load_dotenv

load_dotenv()

# Токен Telegram-бота (обязательно)
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# URL бэкенда photogen
BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")


def validate():
    """Проверяет что все обязательные настройки заполнены."""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан. Заполни .env файл.")
