"""
config.py — Модуль конфигурации.

Загружает настройки из файла .env и делает их доступными
для остальных модулей проекта.
"""

import os
from dotenv import load_dotenv

# Загружаем переменные из файла .env в переменные окружения
load_dotenv()

# --- Настройки Telegram-бота ---
# Токен бота, полученный у @BotFather
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# --- Настройки парсера ---
# Интервал между проверками новых вакансий (в минутах)
CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))

# Включённые источники вакансий (через запятую).
# Примеры: "hh", "superjob", "hh,superjob"
ENABLED_SOURCES: list[str] = [
    s.strip().lower()
    for s in (os.getenv("ENABLED_SOURCES", "hh") or "hh").split(",")
    if s.strip()
]

# Поисковый запрос для HeadHunter API
HH_SEARCH_QUERY: str = os.getenv(
    "HH_SEARCH_QUERY",
    "менеджер маркетплейсов ozon wildberries",
)

# User-Agent для запросов к hh.ru (через SSH туннель с VPS)
HH_USER_AGENT: str = os.getenv(
    "HH_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
)

# Режим получения HTML страниц hh.ru:
#   "direct" — напрямую через aiohttp (использовать, когда бот работает НА VPS)
#   "ssh"    — через SSH на зарубежный VPS (когда бот запущен из РФ)
HH_FETCH_MODE: str = os.getenv("HH_FETCH_MODE", "direct").strip().lower()

# --- Настройки SSH-доступа к VPS (нужны только если HH_FETCH_MODE=ssh) ---
HH_SSH_HOST: str = os.getenv("HH_SSH_HOST", "")
HH_SSH_USER: str = os.getenv("HH_SSH_USER", "root")
HH_SSH_KEY_PATH: str = os.path.expanduser(
    os.getenv("HH_SSH_KEY_PATH", "~/.ssh/id_ed25519_vps")
)

# Secret key приложения SuperJob (X-Api-App-Id) — запасной источник.
# Получить бесплатно: https://api.superjob.ru/register/
SUPERJOB_API_KEY: str = os.getenv("SUPERJOB_API_KEY", "")

# --- Настройки базы данных ---
# Путь к файлу SQLite-базы (лежит рядом с проектом)
DATABASE_PATH: str = os.path.join(os.path.dirname(__file__), "bot_database.db")
