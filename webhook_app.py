"""Точка входа для деплоя на Render (free web service, спящий тариф).

Один фоновый event loop на весь процесс: в нём живут Bot, планировщик
напоминаний и все обращения к SQLite. Flask-воркер только принимает POST от
Telegram и перекидывает апдейт в этот loop через run_coroutine_threadsafe.

ponytail: так сделано намеренно. Раньше на каждый вебхук создавался свой
asyncio.run() со своим loop'ом, и он конкурировал за файл базы с loop'ом
напоминаний — SQLite отдавал "database is locked" на выборе даты. Один loop =
обращения к базе выстраиваются в очередь, конкуренции нет.

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

_loop = asyncio.new_event_loop()
_bot: Bot | None = None
_ready = threading.Event()


def _run_loop() -> None:
    asyncio.set_event_loop(_loop)

    async def _setup() -> None:
        global _bot
        # init_db переключает базу в WAL — это должно случиться до того, как
        # появятся другие соединения, поэтому строго первым делом.
        await storage.init_db()
        _bot = Bot(token=config.BOT_TOKEN, session=AiohttpSession(timeout=5))
        reminders.start(_bot)

    _loop.run_until_complete(_setup())
    _ready.set()
    _loop.run_forever()


threading.Thread(target=_run_loop, daemon=True, name="bot-loop").start()


@app.route("/" + config.BOT_TOKEN, methods=["POST"])
def webhook():
    # На холодном старте Render loop может ещё подниматься — ждём инициализацию,
    # иначе первый апдейт после пробуждения упрётся в _bot = None.
    if not _ready.wait(30):
        return "starting", 503
    update = Update.model_validate(request.get_json(force=True))
    future = asyncio.run_coroutine_threadsafe(dp.feed_update(_bot, update), _loop)
    try:
        future.result(timeout=50)
    except Exception:
        logging.exception("Ошибка обработки апдейта")
    # Отвечаем ok даже при ошибке: на не-200 Telegram ретраит тот же апдейт и
    # зацикливается на упавшем. Причина уже в логах.
    return "ok"


@app.route("/")
def index():
    return "booking bot alive"
