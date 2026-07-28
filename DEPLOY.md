# Деплой booking_bot на Render (бесплатный тариф)

Готово в коде: `webhook_app.py`, `requirements.txt` (добавлены `flask`, `gunicorn`).
Дальше — ручные шаги на сайтах, я их не могу сделать за тебя (вход через GitHub,
создание сервиса).

## 1. Репозиторий на GitHub

Код должен лежать в GitHub — Render деплоит именно оттуда. `.env` и `*.db` уже в
`.gitignore`, токен и база в репозиторий не попадут.

## 2. Создание сервиса на Render

1. https://render.com → «Get Started» → «Login with GitHub» (входишь через кнопку
   в браузере, пароль руками не вводишь).
2. New → Web Service → выбрать репозиторий с `booking_bot`.
3. Настройки:
   - **Root Directory**: `booking_bot` (если бот не в корне репозитория)
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn webhook_app:app`
   - **Instance Type**: Free
4. Environment → добавить переменные:
   - `BOT_TOKEN` — из @BotFather
   - `ADMIN_CHAT_ID` — свой user_id (через @userinfobot)
5. Create Web Service — Render соберёт и задеплоит, выдаст адрес вида
   `https://booking-bot-xxxx.onrender.com`.

## 3. Прописать вебхук в Telegram

Bot API должен узнать, куда слать апдейты. Одна команда (подставь свой токен и
адрес из шага 2):

```
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<твой-сервис>.onrender.com/<BOT_TOKEN>"
```

Ответ `{"ok":true,...}` — вебхук установлен. Написать боту `/start` в Telegram —
первый ответ придёт с задержкой 30–60 сек (холодный старт спящего тарифа), дальше
быстро, пока сервис не заснёт снова через ~15 мин бездействия.

## Про сон и базу (напоминание)

Свободный тариф Render стирает файловую систему при каждом уходе в сон/передеплое
— значит `booking.db` очищается, тестовые записи не переживают простой. Для
портфолио-демо это осознанный компромисс (см. обсуждение в чате) — бот всё равно
показывает весь функционал в моменте теста, просто не хранит историю долго.
