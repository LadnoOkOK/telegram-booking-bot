"""Сценарий клиента: запись, свои записи, отмена, контакты."""

import logging
import re
from datetime import date

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import business
import slots
import storage
from config import ADMIN_CHAT_IDS

router = Router()

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


class Booking(StatesGroup):
    waiting_name = State()
    waiting_phone = State()


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


async def ack(callback: CallbackQuery, text: str = "") -> None:
    # Первым делом гасим крутилку: любой запрос перед answer добавляется
    # к видимой задержке кнопки. Протухший callback (>15 c) не роняет апдейт.
    try:
        await callback.answer(text)
    except TelegramBadRequest:
        pass


async def edit(callback: CallbackQuery, text: str, markup=None) -> None:
    """Повторное нажатие часто даёт тот же текст — Telegram отвечает ошибкой, глотаем."""
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


def human_date(day: date | str) -> str:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    return f"{day.day} {MONTHS[day.month - 1]} ({WEEKDAYS[day.weekday()]})"


def service_name(service_id: str) -> str:
    service = slots.service(service_id)
    return service["name"] if service else service_id


def booking_card(row) -> str:
    return (
        f"🧾 {service_name(row['service_id'])}\n"
        f"📅 {human_date(row['date'])}, {row['start_time']}\n"
        f"👤 {row['name']}, {row['phone']}"
    )


def menu_kb():
    kb = InlineKeyboardBuilder()
    kb.row(btn("📅 Записаться", "book"))
    kb.row(btn("🗂 Мои записи", "my"), btn("ℹ️ Контакты", "contacts"))
    return kb.as_markup()


def services_kb():
    kb = InlineKeyboardBuilder()
    for service in business.SERVICES:
        kb.row(btn(f"{service['name']} — {service['price']} {business.CURRENCY}", f"svc:{service['id']}"))
    kb.row(btn("⬅️ Меню", "menu"))
    return kb.as_markup()


def days_kb():
    kb = InlineKeyboardBuilder()
    for day in slots.available_days():
        kb.button(text=human_date(day), callback_data=f"day:{day.isoformat()}")
    kb.adjust(2)
    kb.row(btn("⬅️ Назад", "book"))
    return kb.as_markup()


def times_kb(free: list[str]):
    kb = InlineKeyboardBuilder()
    for start in free:
        kb.button(text=start, callback_data=f"time:{start}")
    kb.adjust(4)
    kb.row(btn("⬅️ Другая дата", "svc_back"))
    return kb.as_markup()


async def notify_admins(bot: Bot, text: str, markup=None) -> None:
    for chat_id in ADMIN_CHAT_IDS:
        try:
            await bot.send_message(chat_id, text, reply_markup=markup)
        except Exception:  # чат не создан, бот заблокирован — не роняем запись клиента
            logging.exception("Не удалось уведомить админа %s", chat_id)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"👋 {business.BUSINESS_NAME}\n{business.BUSINESS_DESCRIPTION}",
        reply_markup=menu_kb(),
    )


@router.callback_query(F.data == "menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await ack(callback)
    await state.clear()
    await edit(callback, f"👋 {business.BUSINESS_NAME}\n{business.BUSINESS_DESCRIPTION}", menu_kb())


@router.callback_query(F.data == "contacts")
async def show_contacts(callback: CallbackQuery) -> None:
    await ack(callback)
    kb = InlineKeyboardBuilder()
    kb.row(btn("⬅️ Меню", "menu"))
    await edit(callback, business.CONTACTS, kb.as_markup())


@router.callback_query(F.data == "book")
async def choose_service(callback: CallbackQuery, state: FSMContext) -> None:
    await ack(callback)
    await state.set_state(None)
    await edit(callback, "Выберите услугу:", services_kb())


@router.callback_query(F.data.startswith("svc:"))
async def choose_day(callback: CallbackQuery, state: FSMContext) -> None:
    await ack(callback)
    service_id = callback.data.split(":", 1)[1]
    if not slots.service(service_id):
        return await edit(callback, "Услуга больше не доступна.", services_kb())
    await state.update_data(service_id=service_id)
    await edit(callback, f"{service_name(service_id)}\nВыберите дату:", days_kb())


@router.callback_query(F.data == "svc_back")
async def back_to_days(callback: CallbackQuery, state: FSMContext) -> None:
    await ack(callback)
    data = await state.get_data()
    if not data.get("service_id"):
        return await edit(callback, "Выберите услугу:", services_kb())
    await edit(callback, f"{service_name(data['service_id'])}\nВыберите дату:", days_kb())


@router.callback_query(F.data.startswith("day:"))
async def choose_time(callback: CallbackQuery, state: FSMContext) -> None:
    await ack(callback)
    data = await state.get_data()
    service = slots.service(data.get("service_id", ""))
    if not service:
        return await edit(callback, "Начнём заново — выберите услугу:", services_kb())

    day = callback.data.split(":", 1)[1]
    busy = await storage.busy_intervals(day)
    free = slots.free_slots(date.fromisoformat(day), service["duration_min"], busy)
    if not free:
        return await edit(callback, f"{human_date(day)} — свободных окон нет. Выберите другую дату:", days_kb())

    await state.update_data(day=day)
    await edit(callback, f"{service['name']}, {human_date(day)}\nВыберите время:", times_kb(free))


@router.callback_query(F.data.startswith("time:"))
async def collect_contacts(callback: CallbackQuery, state: FSMContext) -> None:
    await ack(callback)
    data = await state.get_data()
    if not data.get("service_id") or not data.get("day"):
        return await edit(callback, "Начнём заново — выберите услугу:", services_kb())

    await state.update_data(start=callback.data.split(":", 1)[1])
    client = await storage.get_client(callback.from_user.id)
    if client:
        text, markup = await confirm_screen(state, client)
        return await edit(callback, text, markup)

    await state.set_state(Booking.waiting_name)
    await edit(callback, "Как вас зовут? Напишите имя одним сообщением.")


async def confirm_screen(state: FSMContext, client) -> tuple[str, object]:
    data = await state.get_data()
    service = slots.service(data["service_id"])
    text = (
        "Проверьте запись:\n\n"
        f"🧾 {service['name']} — {service['price']} {business.CURRENCY}\n"
        f"📅 {human_date(data['day'])}, {data['start']} ({service['duration_min']} мин)\n"
        f"👤 {client['name']}\n"
        f"📱 {client['phone']}"
    )
    kb = InlineKeyboardBuilder()
    kb.row(btn("✅ Подтвердить", "confirm"))
    kb.row(btn("✏️ Изменить", "book"), btn("❌ Отмена", "menu"))
    return text, kb.as_markup()


@router.message(Booking.waiting_name)
async def got_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 50:
        return await message.answer("Нужно имя от 2 до 50 символов. Попробуйте ещё раз.")

    await state.update_data(name=name)
    await state.set_state(Booking.waiting_phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить контакт", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        f"Приятно познакомиться, {name}!\nОставьте телефон — кнопкой ниже или текстом.",
        reply_markup=kb,
    )


def normalize_phone(text: str) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return f"+{digits}" if 10 <= len(digits) <= 15 else None


@router.message(Booking.waiting_phone)
async def got_phone(message: Message, state: FSMContext) -> None:
    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw or "")
    if not phone:
        return await message.answer("Не похоже на телефон. Пример: +7 900 123-45-67")

    data = await state.get_data()
    await storage.save_client(message.from_user.id, data["name"], phone)
    await state.set_state(None)
    await message.answer("Спасибо!", reply_markup=ReplyKeyboardRemove())

    client = await storage.get_client(message.from_user.id)
    text, markup = await confirm_screen(state, client)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "confirm")
async def confirm_booking(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ack(callback)
    data = await state.get_data()
    service = slots.service(data.get("service_id", ""))
    client = await storage.get_client(callback.from_user.id)
    if not service or not data.get("day") or not data.get("start") or not client:
        # Повторное нажатие: черновик уже очищен первым — просто выходим в меню
        return await edit(callback, "Запись уже оформлена или устарела.", menu_kb())

    await state.clear()
    end = slots.slot_end(data["start"], service["duration_min"])
    booking_id = await storage.create_booking(
        client["id"], service["id"], data["day"], data["start"], end
    )
    if booking_id is None:
        await state.update_data(service_id=service["id"])
        return await edit(callback, "Увы, это время только что заняли. Выберите другое:", days_kb())

    await edit(
        callback,
        "✅ Заявка принята!\n\n"
        f"🧾 {service['name']} — {service['price']} {business.CURRENCY}\n"
        f"📅 {human_date(data['day'])}, {data['start']}\n\n"
        "Администратор подтвердит запись, мы сразу напишем.",
        menu_kb(),
    )

    kb = InlineKeyboardBuilder()
    kb.row(btn("✅ Подтвердить", f"adm:ok:{booking_id}"), btn("❌ Отклонить", f"adm:no:{booking_id}"))
    row = await storage.get_booking(booking_id)
    await notify_admins(bot, f"🆕 Новая запись #{booking_id}\n\n{booking_card(row)}", kb.as_markup())


@router.callback_query(F.data == "my")
async def my_bookings(callback: CallbackQuery) -> None:
    await ack(callback)
    rows = await storage.upcoming(callback.from_user.id, slots.now())
    kb = InlineKeyboardBuilder()
    if not rows:
        text = "У вас нет предстоящих записей."
    else:
        lines = ["🗂 Ваши записи:\n"]
        for row in rows:
            mark = "✅" if row["status"] == "confirmed" else "⏳"
            lines.append(
                f"{mark} {human_date(row['date'])}, {row['start_time']} — {service_name(row['service_id'])}"
            )
            kb.row(btn(f"❌ Отменить {row['start_time']} {human_date(row['date'])}", f"cancel:{row['id']}"))
        text = "\n".join(lines)
    kb.row(btn("⬅️ Меню", "menu"))
    await edit(callback, text, kb.as_markup())


@router.callback_query(F.data.startswith("cancel:"))
async def ask_cancel(callback: CallbackQuery) -> None:
    await ack(callback)
    booking_id = int(callback.data.split(":")[1])
    row = await storage.get_booking(booking_id)
    if not row or row["tg_user_id"] != callback.from_user.id or row["status"] == "cancelled":
        return await edit(callback, "Запись не найдена или уже отменена.", menu_kb())

    kb = InlineKeyboardBuilder()
    kb.row(btn("Да, отменить", f"cancel_yes:{booking_id}"), btn("Нет", "my"))
    await edit(callback, f"Отменить запись?\n\n{booking_card(row)}", kb.as_markup())


@router.callback_query(F.data.startswith("cancel_yes:"))
async def do_cancel(callback: CallbackQuery, bot: Bot) -> None:
    await ack(callback)
    booking_id = int(callback.data.split(":")[1])
    row = await storage.get_booking(booking_id)
    if not row or row["tg_user_id"] != callback.from_user.id:
        return await edit(callback, "Запись не найдена.", menu_kb())

    cancelled = await storage.set_status(booking_id, "cancelled", only_if=row["status"])
    if not cancelled:
        return await edit(callback, "Запись уже отменена.", menu_kb())

    await edit(callback, "Запись отменена. Слот снова свободен.", menu_kb())
    await notify_admins(bot, f"🚫 Клиент отменил запись #{booking_id}\n\n{booking_card(row)}")
