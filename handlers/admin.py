"""Сторона администратора: подтверждение/отклонение записей и /today."""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import slots
import storage
from config import ADMIN_CHAT_IDS
from handlers.client import ack, booking_card, edit, human_date, service_name

router = Router()


def is_admin(user_id: int, chat_id: int) -> bool:
    return user_id in ADMIN_CHAT_IDS or chat_id in ADMIN_CHAT_IDS


@router.message(Command("today"))
async def today(message: Message) -> None:
    if not is_admin(message.from_user.id, message.chat.id):
        return

    day = slots.now().date()
    rows = await storage.on_date(day.isoformat())
    if not rows:
        return await message.answer(f"На {human_date(day)} записей нет.")

    lines = [f"📋 Записи на {human_date(day)}:\n"]
    for row in rows:
        mark = "✅" if row["status"] == "confirmed" else "⏳"
        lines.append(
            f"{mark} {row['start_time']}–{row['end_time']} — {service_name(row['service_id'])}\n"
            f"     {row['name']}, {row['phone']}"
        )
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("adm:"))
async def decide(callback: CallbackQuery, bot: Bot) -> None:
    await ack(callback)
    if not is_admin(callback.from_user.id, callback.message.chat.id):
        return

    _, action, raw_id = callback.data.split(":")
    booking_id = int(raw_id)
    row = await storage.get_booking(booking_id)
    if not row:
        return await edit(callback, f"Запись #{booking_id} не найдена.")

    status = "confirmed" if action == "ok" else "cancelled"
    # only_if='pending' — второе нажатие вернёт False и ничего не отправит клиенту
    if not await storage.set_status(booking_id, status):
        return await edit(callback, f"{booking_card(row)}\n\nУже обработана: {row['status']}.")

    if status == "confirmed":
        label = "✅ Подтверждена"
        text = (
            f"✅ Запись подтверждена!\n\n{service_name(row['service_id'])}\n"
            f"📅 {human_date(row['date'])}, {row['start_time']}\n\nЖдём вас!"
        )
    else:
        label = "❌ Отклонена"
        text = (
            f"К сожалению, время {human_date(row['date'])} {row['start_time']} не получится подтвердить.\n"
            "Пожалуйста, выберите другое — /start"
        )

    await edit(callback, f"{booking_card(row)}\n\n{label}")
    try:
        await bot.send_message(row["tg_user_id"], text)
    except Exception:  # клиент заблокировал бота — статус уже проставлен, это нормально
        pass
