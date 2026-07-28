import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

import config
import reminders
import storage
from handlers import admin, client


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Заполни .env (см. .env.example)")

    await storage.init_db()

    # timeout=5: одна медленная отправка не должна тормозить весь процесс
    bot = Bot(token=config.BOT_TOKEN, session=AiohttpSession(timeout=5))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(client.router)
    dp.include_router(admin.router)

    reminders.start(bot)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
