"""SQLite через aiosqlite. Соединение открывается на запрос — объёмы записи такие,
что пул не окупается."""

from contextlib import asynccontextmanager
from datetime import datetime

import aiosqlite

from config import DB_PATH

ACTIVE = ("pending", "confirmed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    service_id TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL,
    reminder_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date, status);
"""

_BOOKING_FIELDS = """
    b.id, b.client_id, b.service_id, b.date, b.start_time, b.end_time, b.status,
    c.tg_user_id, c.name, c.phone
"""


async def _tune(db: aiosqlite.Connection) -> None:
    # ponytail: без этого конкурентный доступ (вебхук-запрос + фоновый поток
    # напоминаний, оба бьют в один файл) роняет чтения с "database is locked" —
    # busy_timeout заставляет SQLite подождать и повторить вместо мгновенной
    # ошибки, WAL разрешает читателям работать, пока идёт запись.
    await db.execute("PRAGMA busy_timeout = 5000")
    await db.execute("PRAGMA journal_mode = WAL")


@asynccontextmanager
async def _db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _tune(db)
        yield db


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _tune(db)
        await db.executescript(SCHEMA)
        await db.commit()


async def get_client(tg_user_id: int) -> aiosqlite.Row | None:
    async with _db() as db:
        cur = await db.execute("SELECT * FROM clients WHERE tg_user_id = ?", (tg_user_id,))
        return await cur.fetchone()


async def save_client(tg_user_id: int, name: str, phone: str) -> int:
    async with _db() as db:
        await db.execute(
            """INSERT INTO clients (tg_user_id, name, phone, created_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(tg_user_id) DO UPDATE SET name = excluded.name, phone = excluded.phone""",
            (tg_user_id, name, phone, datetime.now().isoformat()),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM clients WHERE tg_user_id = ?", (tg_user_id,))
        row = await cur.fetchone()
        return row["id"]


async def busy_intervals(day: str) -> list[tuple[str, str]]:
    async with _db() as db:
        cur = await db.execute(
            f"SELECT start_time, end_time FROM bookings WHERE date = ? AND status IN {ACTIVE}",
            (day,),
        )
        return [(row["start_time"], row["end_time"]) for row in await cur.fetchall()]


async def create_booking(
    client_id: int, service_id: str, day: str, start: str, end: str
) -> int | None:
    """Проверка пересечения и вставка в одной транзакции — иначе два клиента
    успевают занять один слот между SELECT и INSERT. None = слот уже занят."""
    async with aiosqlite.connect(DB_PATH, isolation_level=None) as db:
        await _tune(db)
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute(
            f"""SELECT 1 FROM bookings
                WHERE date = ? AND status IN {ACTIVE} AND start_time < ? AND ? < end_time
                LIMIT 1""",
            (day, end, start),
        )
        if await cur.fetchone():
            await db.execute("ROLLBACK")
            return None
        cur = await db.execute(
            """INSERT INTO bookings
               (client_id, service_id, date, start_time, end_time, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (client_id, service_id, day, start, end, datetime.now().isoformat()),
        )
        await db.execute("COMMIT")
        return cur.lastrowid


async def get_booking(booking_id: int) -> aiosqlite.Row | None:
    async with _db() as db:
        cur = await db.execute(
            f"SELECT {_BOOKING_FIELDS} FROM bookings b JOIN clients c ON c.id = b.client_id"
            " WHERE b.id = ?",
            (booking_id,),
        )
        return await cur.fetchone()


async def set_status(booking_id: int, status: str, only_if: str = "pending") -> bool:
    """False = запись уже не в состоянии only_if. На этом держится идемпотентность
    админских кнопок и отмены: повторное нажатие ничего не меняет."""
    async with _db() as db:
        cur = await db.execute(
            "UPDATE bookings SET status = ? WHERE id = ? AND status = ?",
            (status, booking_id, only_if),
        )
        await db.commit()
        return cur.rowcount > 0


async def upcoming(tg_user_id: int, after: datetime) -> list[aiosqlite.Row]:
    async with _db() as db:
        cur = await db.execute(
            f"""SELECT {_BOOKING_FIELDS} FROM bookings b JOIN clients c ON c.id = b.client_id
                WHERE c.tg_user_id = ? AND b.status IN {ACTIVE}
                  AND b.date || ' ' || b.start_time >= ?
                ORDER BY b.date, b.start_time""",
            (tg_user_id, after.strftime("%Y-%m-%d %H:%M")),
        )
        return await cur.fetchall()


async def on_date(day: str) -> list[aiosqlite.Row]:
    async with _db() as db:
        cur = await db.execute(
            f"""SELECT {_BOOKING_FIELDS} FROM bookings b JOIN clients c ON c.id = b.client_id
                WHERE b.date = ? AND b.status IN {ACTIVE}
                ORDER BY b.start_time""",
            (day,),
        )
        return await cur.fetchall()


async def due_reminders(now: datetime, until: datetime) -> list[aiosqlite.Row]:
    async with _db() as db:
        cur = await db.execute(
            f"""SELECT {_BOOKING_FIELDS} FROM bookings b JOIN clients c ON c.id = b.client_id
                WHERE b.status IN {ACTIVE} AND b.reminder_sent = 0
                  AND b.date || ' ' || b.start_time BETWEEN ? AND ?""",
            (now.strftime("%Y-%m-%d %H:%M"), until.strftime("%Y-%m-%d %H:%M")),
        )
        return await cur.fetchall()


async def mark_reminder_sent(booking_id: int) -> None:
    async with _db() as db:
        await db.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (booking_id,))
        await db.commit()
