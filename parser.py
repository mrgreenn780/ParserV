"""
parser.py — единая точка входа для парсеров вакансий.

Выбирает конкретную реализацию по переменной окружения HH_FETCH_MODE:
    - "direct" (по умолчанию): прямой aiohttp-запрос к hh.ru.
      Нужен, когда процесс бота САМ запущен на зарубежном VPS.
    - "ssh": запрос выполняется на удалённом VPS через SSH.
      Нужен, когда бот запущен в РФ и не может сам достучаться до hh.ru.
"""

from __future__ import annotations

from config import HH_FETCH_MODE

if HH_FETCH_MODE == "ssh":
    from parser_hh_via_ssh import fetch_vacancies, format_vacancy_message
else:
    from parser_hh_direct import fetch_vacancies, format_vacancy_message


__all__ = ["fetch_vacancies", "format_vacancy_message"]
