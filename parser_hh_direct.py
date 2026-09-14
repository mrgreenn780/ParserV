"""
parser_hh_direct.py — прямой парсер hh.ru через aiohttp.

Используется, когда бот САМ работает на зарубежном VPS:
ходим на hh.ru напрямую (без SSH-прослойки), тянем HTML-страницу поиска
и вытаскиваем JSON HH-Lux-InitialState.

Общие функции (разбор JSON, нормализация вакансии, format_vacancy_message)
переиспользуются из parser_hh_via_ssh.
"""

from __future__ import annotations

import urllib.parse

import aiohttp

from config import HH_SEARCH_QUERY, HH_USER_AGENT
from database import is_vacancy_seen
from parser_hh_via_ssh import (
    _extract_state,
    _extract_vacancies_list,
    _normalize,
    format_vacancy_message,
)


_BASE_URL = "https://hh.ru/search/vacancy"

_HEADERS = {
    "User-Agent": HH_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
}


async def fetch_vacancies() -> list[dict]:
    """
    Забирает свежие вакансии с hh.ru (прямой HTTP-запрос).
    Возвращает только НОВЫЕ (которых нет в БД).
    """

    params = {
        "text": HH_SEARCH_QUERY,
        "items_on_page": 50,
        "order_by": "publication_time",
        "search_period": 1,
    }
    url = f"{_BASE_URL}?{urllib.parse.urlencode(params)}"

    timeout = aiohttp.ClientTimeout(total=40)
    async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status == 403:
                raise PermissionError(
                    f"hh.ru вернул 403 — IP сервера попал в бан-лист. "
                    f"Попробуй поднять бота на другом VPS."
                )
            if resp.status != 200:
                body_preview = (await resp.text())[:300]
                raise RuntimeError(f"hh.ru HTTP {resp.status}: {body_preview}")

            html = await resp.text()

    print(f"[HH/direct] GET {url[:90]}... -> HTTP 200, {len(html)} bytes")

    state = _extract_state(html)
    items = _extract_vacancies_list(state)
    print(f"[HH/direct] Всего вакансий в выдаче: {len(items)}")

    new_vacancies: list[dict] = []
    for item in items:
        vid = item.get("vacancyId")
        if vid is None:
            continue
        vacancy_id = f"hh:{vid}"
        if is_vacancy_seen(vacancy_id):
            continue
        new_vacancies.append(_normalize(item, vacancy_id))

    print(f"[HH/direct] Из них новых: {len(new_vacancies)}")
    return new_vacancies


__all__ = ["fetch_vacancies", "format_vacancy_message"]
