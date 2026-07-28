"""Напоминания клиентам за REMINDER_BEFORE_HOURS часов до визита."""

import logging
from datetime import timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import business
import slots
import storage

CHECK_EVERY_MIN = 5


async def send_due(bot: Bot) -> None:
    now = slots.now()
    until = now + timedelta(hours=business.REMINDER_BEFORE_HOURS)

    for row in await storage.due_reminders(now, until):
        service = slots.service(row["service_id"])
        name = service["name"] if service else row["service_id"]
        when = "сегодня" if row["date"] == now.date().isoformat() else "завтра"
        try:
            await bot.send_message(
                row["tg_user_id"],
                f"⏰ Напоминаем: {when} в {row['start_time']} у вас запись — {name}.",
            )
        except Exception:
            logging.exception("Напоминание #%s не доставлено", row["id"])
            continue
        await storage.mark_reminder_sent(row["id"])


def start(bot: Bot) -> AsyncIOScheduler:
    """Состояние живёт в bookings.reminder_sent, а не в планировщике — поэтому
    перезапуск процесса не задваивает и не теряет напоминания."""
    scheduler = AsyncIOScheduler(timezone=business.TIMEZONE)
    scheduler.add_job(send_due, "interval", minutes=CHECK_EVERY_MIN, args=[bot])
    scheduler.start()
    return scheduler
