"""Точка входа для деплоя на Render (free web service, спящий тариф).

В отличие от eva_bot, здесь есть фоновые напоминания (APScheduler) — им нужен
долгоживущий event loop с постоянным Bot/session, а не новый Bot на каждый
HTTP-запрос. Поэтому: отдельный поток со своим loop поднимает планировщик один
раз при старте процесса, а обработка вебхука по-прежнему открывает свежий Bot
на каждый апдейт (тот же приём, что в eva_bot/webhook_app.py, и по той же
причине — Bot, созданный при импорте, был бы привязан к чужому loop).

ponytail: на бесплатном тарифе процесс засыпает после ~15 мин без запросов —
пока он спит, планировщик тоже не тикает, напоминания уйдут при следующем
пробуждении (следующий вебхук). Это ограничение тарифа, не баг.
"""

import asyncio
import logging
import threading

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from flask import Flask, request

import config
import reminders
import storage
from handlers import admin, client

logging.basicConfig(level=logging.INFO)

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(client.router)
dp.include_router(admin.router)

app = Flask(__name__)


def _run_scheduler() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _setup() -> None:
        await storage.init_db()
        bot = Bot(token=config.BOT_TOKEN, session=AiohttpSession(timeout=5))
        reminders.start(bot)

    loop.run_until_complete(_setup())
    loop.run_forever()


threading.Thread(target=_run_scheduler, daemon=True, name="reminders-loop").start()


async def _handle_update(update: Update) -> None:
    # ponytail: свежий Bot (и его aiohttp-сессия) на каждый запрос, в своём же
    # event loop — Bot, созданный при импорте модуля, держит сессию, привязанную
    # к тому loop'у, в котором был создан, а asyncio.run() открывает новый loop
    # на каждый вызов, так что последующие запросы упирались бы в закрытый loop.
    session = AiohttpSession(timeout=5)
    bot = Bot(token=config.BOT_TOKEN, session=session)
    try:
        await dp.feed_update(bot, update)
    finally:
        await bot.session.close()


@app.route("/" + config.BOT_TOKEN, methods=["POST"])
def webhook():
    update = Update.model_validate(request.get_json(force=True))
    asyncio.run(_handle_update(update))
    return "ok"


@app.route("/")
def index():
    return "booking bot alive"
