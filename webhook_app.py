"""Точка входа для деплоя на Render (free web service, спящий тариф).

Здесь намеренно нет фонового потока с планировщиком — только Flask и по одному
короткоживущему event loop'у на каждый апдейт. Причины две:

1. Планировщик на спящем тарифе всё равно почти бесполезен: пока процесс спит,
   он не тикает. Напоминания реально уходят только когда сервис разбудил
   входящий вебхук — значит проще проверять их прямо в обработчике вебхука.
2. Второй поток со своим loop'ом конкурировал с обработчиком вебхука за файл
   SQLite, и база отдавала "database is locked" на выборе даты. Без него в
   каждый момент времени с базой работает ровно одно соединение.

Для локальной разработки остаётся bot.py (long polling + APScheduler).
"""

import asyncio
import logging
import time

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

# Как часто догонять напоминания. Гоняться на каждом апдейте незачем — запрос к
# базе дешёвый, но лишний.
REMINDER_INTERVAL_SEC = 300

_initialized = False
_last_reminder_check = 0.0


async def _handle_update(update: Update) -> None:
    global _initialized, _last_reminder_check

    # Свежий Bot на каждый запрос: сессия aiohttp привязана к тому loop'у, в
    # котором создана, а asyncio.run() каждый раз открывает новый.
    bot = Bot(token=config.BOT_TOKEN, session=AiohttpSession(timeout=5))
    try:
        if not _initialized:
            # Диск на free-тарифе эфемерный: после каждого сна/передеплоя базы
            # нет, поэтому схему создаём при первом апдейте после старта.
            await storage.init_db()
            _initialized = True

        await dp.feed_update(bot, update)

        if time.monotonic() - _last_reminder_check > REMINDER_INTERVAL_SEC:
            _last_reminder_check = time.monotonic()
            await reminders.send_due(bot)
    finally:
        await bot.session.close()


@app.route("/" + config.BOT_TOKEN, methods=["POST"])
def webhook():
    update = Update.model_validate(request.get_json(force=True))
    try:
        asyncio.run(_handle_update(update))
    except Exception:
        logging.exception("Ошибка обработки апдейта")
    # Отвечаем ok даже при ошибке: на не-200 Telegram ретраит тот же апдейт и
    # зацикливается на упавшем. Причина уже в логах.
    return "ok"


@app.route("/")
def index():
    return "booking bot alive"
