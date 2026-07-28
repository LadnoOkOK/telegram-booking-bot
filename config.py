import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", str(Path(__file__).resolve().parent / "booking.db"))

_admins = os.getenv("ADMIN_CHAT_ID", "").strip()
ADMIN_CHAT_IDS = [int(x) for x in _admins.split(",") if x.strip()]
