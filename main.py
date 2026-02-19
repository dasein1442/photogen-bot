import asyncio
import logging

from aiogram import Bot, Dispatcher

from app import config
from app.handlers import get_all_routers


async def main():
    config.validate()

    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Подключаем обработчики
    for router in get_all_routers():
        dp.include_router(router)

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
