"""Проверка сетки слотов и защиты от двойного бронирования.

Запуск: python test_slots.py (или pytest test_slots.py)
"""

import asyncio
import os
import tempfile
from datetime import date, datetime

os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "booking_test.db"))

import business  # noqa: E402
import slots  # noqa: E402
import storage  # noqa: E402

MONDAY = date(2026, 8, 3)   # 10:00–19:00 по business.WORKING_HOURS
SUNDAY = date(2026, 8, 9)   # выходной
PAST = datetime(2026, 8, 3, 0, 0)


def test_slots_fit_service_duration():
    free = slots.free_slots(MONDAY, duration_min=120, busy=[], moment=PAST)
    assert free[0] == "10:00"
    assert free[-1] == "17:00", free[-1]  # 17:00 + 2 ч = 19:00, ровно до закрытия


def test_busy_interval_blocks_overlapping_slots():
    free = slots.free_slots(MONDAY, duration_min=60, busy=[("12:00", "13:00")], moment=PAST)
    assert "11:30" not in free  # 11:30–12:30 налезает на занятое
    assert "12:00" not in free
    assert "11:00" in free      # 11:00–12:00 упирается встык — это можно
    assert "13:00" in free


def test_past_slots_hidden():
    free = slots.free_slots(MONDAY, duration_min=40, busy=[], moment=datetime(2026, 8, 3, 14, 15))
    assert free[0] == "14:30"


def test_day_off_has_no_slots():
    assert slots.free_slots(SUNDAY, duration_min=40, busy=[], moment=PAST) == []
    assert all(d.weekday() != 6 for d in slots.available_days(MONDAY))
    assert len(slots.available_days(MONDAY)) <= business.BOOKING_HORIZON_DAYS


def test_double_booking_is_rejected():
    """Два клиента жмут «Подтвердить» одновременно — слот получает один."""

    async def scenario():
        if os.path.exists(storage.DB_PATH):
            os.remove(storage.DB_PATH)
        await storage.init_db()
        first = await storage.save_client(1, "Первый", "+79000000001")
        second = await storage.save_client(2, "Второй", "+79000000002")

        results = await asyncio.gather(
            storage.create_booking(first, "haircut", "2026-08-03", "12:00", "12:40"),
            storage.create_booking(second, "haircut", "2026-08-03", "12:30", "13:10"),
        )
        assert sorted(r is None for r in results) == [False, True], results
        assert len(await storage.on_date("2026-08-03")) == 1

        booking_id = next(r for r in results if r)
        assert await storage.set_status(booking_id, "confirmed") is True
        assert await storage.set_status(booking_id, "confirmed") is False  # идемпотентность

    asyncio.run(scenario())


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_"):
            func()
            print(f"ok  {name}")
    print("\nвсе проверки прошли")
