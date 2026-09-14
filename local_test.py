"""
local_test.py — локальный тест парсинга без Telegram.

Зачем:
  - можно спокойно разрабатывать/тестировать парсеры на ПК,
    не останавливая VPS-бота (и не ловить TelegramConflictError).

Запуск:
  .\\venv\\Scripts\\python.exe -u local_test.py
"""

from __future__ import annotations

import asyncio
import sys

from database import init_db
from config import ENABLED_SOURCES
from aggregator import fetch_vacancies_for_sources, format_vacancy_message


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    init_db()
    items = await fetch_vacancies_for_sources(ENABLED_SOURCES)
    print(f"NEW_COUNT={len(items)}")
    for v in items[:5]:
        print("-" * 60)
        print(format_vacancy_message(v))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

