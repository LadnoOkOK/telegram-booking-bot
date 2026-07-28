"""Сетка слотов и пересечения. Чистые функции — вся ниша приходит из business.py."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import business

TZ = ZoneInfo(business.TIMEZONE)


def now() -> datetime:
    """Локальное время бизнеса, naive — сравнивать с датами/временем из БД."""
    return datetime.now(TZ).replace(tzinfo=None)


def _hm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def working_hours(day: date) -> tuple[time, time] | None:
    hours = business.WORKING_HOURS.get(day.weekday())
    return (_hm(hours[0]), _hm(hours[1])) if hours else None


def service(service_id: str) -> dict | None:
    return next((s for s in business.SERVICES if s["id"] == service_id), None)


def available_days(today: date | None = None) -> list[date]:
    today = today or now().date()
    days = (today + timedelta(days=i) for i in range(business.BOOKING_HORIZON_DAYS))
    return [d for d in days if working_hours(d)]


def slot_end(start: str, duration_min: int) -> str:
    end = datetime.combine(date.min, _hm(start)) + timedelta(minutes=duration_min)
    return end.strftime("%H:%M")


def free_slots(
    day: date,
    duration_min: int,
    busy: list[tuple[str, str]],
    moment: datetime | None = None,
) -> list[str]:
    """Свободные начала визита на день с учётом длительности услуги.

    busy — уже занятые интервалы ("HH:MM", "HH:MM"). Строки zero-padded,
    поэтому лексикографическое сравнение совпадает с хронологическим.
    """
    hours = working_hours(day)
    if not hours:
        return []
    opening, closing = hours
    moment = moment or now()
    cursor = datetime.combine(day, opening)
    last = datetime.combine(day, closing)
    step = timedelta(minutes=business.SLOT_STEP_MIN)
    duration = timedelta(minutes=duration_min)

    result = []
    while cursor + duration <= last:
        start = cursor.strftime("%H:%M")
        end = (cursor + duration).strftime("%H:%M")
        overlaps = any(start < busy_end and busy_start < end for busy_start, busy_end in busy)
        if cursor > moment and not overlaps:
            result.append(start)
        cursor += step
    return result
