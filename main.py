import asyncio
import logging

from aiogram import Bot, Dispatcher

from app import config
from app.broker.connection import setup_broker, close_broker
from app.broker.consumer import BotActionConsumer
from app.handlers import get_all_routers
from app.services.analytics_sdk import AnalyticsClient, AiogramAnalyticsMiddleware


async def main():
    config.validate()

    logging.basicConfig(level=logging.INFO)

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Аналитика
    analytics = AnalyticsClient(url=config.ANALYTICS_URL, api_key=config.ANALYTICS_API_KEY, enabled=config.ANALYTICS_ENABLED)
    await analytics.start()

    middleware = AiogramAnalyticsMiddleware(analytics)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)

    dp["analytics"] = analytics

    # Подключаем обработчики
    for router in get_all_routers():
        dp.include_router(router)

    # RabbitMQ consumer
    broker_connection = None
    if config.RABBITMQ_URL:
        broker_connection, broker_channel = await setup_broker(config.RABBITMQ_URL)
        consumer = BotActionConsumer(channel=broker_channel, bot=bot, analytics=analytics)
        await consumer.start()

    # Запускаем бота
    try:
        await dp.start_polling(bot)
    finally:
        await analytics.stop()
        if broker_connection:
            await close_broker(broker_connection)


if __name__ == "__main__":
    asyncio.run(main())
