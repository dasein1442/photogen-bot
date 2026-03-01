import asyncio
import logging

from aiogram import Bot, Dispatcher

from app import config
from app.handlers import get_all_routers
from app.services.analytics_sdk import AnalyticsClient, AiogramAnalyticsMiddleware
from app.middlewares.paywall_guard import PaywallGuardMiddleware


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

    # Paywall guard — blocks actions while in onboarding_paywall state
    paywall_guard = PaywallGuardMiddleware()
    dp.message.middleware(paywall_guard)
    dp.callback_query.middleware(paywall_guard)

    dp["analytics"] = analytics

    # Подключаем обработчики
    for router in get_all_routers():
        dp.include_router(router)

    # Запускаем бота
    try:
        await dp.start_polling(bot)
    finally:
        await analytics.stop()


if __name__ == "__main__":
    asyncio.run(main())
