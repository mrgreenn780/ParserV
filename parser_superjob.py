"""
parser_superjob.py — парсер вакансий через SuperJob Open API.

Документация: https://api.superjob.ru/
Регистрация приложения (бесплатно, без модерации):
    https://api.superjob.ru/register/

Что делает:
  1. Отправляет запрос к https://api.superjob.ru/2.0/vacancies/
     с заголовком X-Api-App-Id (Secret key из личного кабинета SuperJob).
  2. Получает JSON с вакансиями.
  3. Фильтрует только новые (которых нет в нашей БД).
  4. Возвращает список для рассылки.
"""

from __future__ import annotations

import aiohttp

from config import SUPERJOB_API_KEY, HH_SEARCH_QUERY
from database import is_vacancy_seen


SUPERJOB_URL = "https://api.superjob.ru/2.0/vacancies/"

# Человекочитаемый User-Agent — SuperJob не такой придирчивый, как hh.
_USER_AGENT = "job-parser-bot/1.0"


async def fetch_vacancies() -> list[dict]:
    """
    Запрашивает свежие вакансии и возвращает только НОВЫЕ.

    Каждая вакансия — dict с ключами:
      id, title, employer, salary, url, area, snippet
    """

    if not SUPERJOB_API_KEY:
        raise PermissionError(
            "SUPERJOB_API_KEY не задан. Получи ключ на https://api.superjob.ru/register/ "
            "и пропиши в .env: SUPERJOB_API_KEY=<secret_key>"
        )

    params = {
        "keyword": HH_SEARCH_QUERY,
        "count": 50,
        "page": 0,
        "order_field": "date",
        "order_direction": "desc",
        "period": 1,  # дней
    }
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "X-Api-App-Id": SUPERJOB_API_KEY,
    }

    new_vacancies: list[dict] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(SUPERJOB_URL, params=params, headers=headers) as resp:
                body_text = await resp.text()

                if resp.status == 401 or resp.status == 403:
                    raise PermissionError(
                        f"SuperJob отклонил запрос ({resp.status}): {body_text[:300]}"
                    )
                if resp.status != 200:
                    raise RuntimeError(
                        f"SuperJob API {resp.status}: {body_text[:300]}"
                    )

                import json

                data = json.loads(body_text)

        items = data.get("objects", []) or []
        print(f"[SJ] Получено {len(items)} вакансий (total={data.get('total')})")

        for item in items:
            vacancy_id = f"sj:{item['id']}"

            if is_vacancy_seen(vacancy_id):
                continue

            vacancy = {
                "id": vacancy_id,
                "title": item.get("profession") or "Без названия",
                "employer": _get_employer(item),
                "salary": _format_salary(item),
                "url": item.get("link") or "",
                "area": (item.get("town") or {}).get("title", "—"),
                "snippet": _get_snippet(item),
            }
            new_vacancies.append(vacancy)

        print(f"[SJ] Из них новых: {len(new_vacancies)}")

    except aiohttp.ClientError as e:
        print(f"[SJ] Ошибка сети: {e!r}")
    except PermissionError:
        raise
    except Exception as e:
        print(f"[SJ] Непредвиденная ошибка: {e!r}")

    return new_vacancies


def format_vacancy_message(vacancy: dict) -> str:
    lines = [
        f"🔥 <b>{vacancy['title']}</b>",
        f"🏢 {vacancy['employer']}",
        f"📍 {vacancy['area']}",
        f"💰 {vacancy['salary']}",
    ]
    if vacancy["snippet"]:
        lines.append(f"\n📋 <i>{vacancy['snippet']}</i>")
    if vacancy["url"]:
        lines.append(f"\n🔗 <a href=\"{vacancy['url']}\">Открыть вакансию</a>")
    return "\n".join(lines)


# ─── helpers ───────────────────────────────────────────────────────────────

def _get_employer(item: dict) -> str:
    firm = item.get("firm_name")
    if firm:
        return firm
    client = item.get("client") or {}
    return client.get("title") or "Не указан"


def _format_salary(item: dict) -> str:
    pay_from = item.get("payment_from") or 0
    pay_to = item.get("payment_to") or 0
    cur = (item.get("currency") or "rub").lower()
    cur_map = {"rub": "₽", "usd": "$", "eur": "€", "kzt": "₸"}
    cur_sign = cur_map.get(cur, cur.upper())

    def _fmt(v: int) -> str:
        return f"{int(v):,}".replace(",", " ")

    if pay_from and pay_to:
        return f"{_fmt(pay_from)} – {_fmt(pay_to)} {cur_sign}"
    if pay_from:
        return f"от {_fmt(pay_from)} {cur_sign}"
    if pay_to:
        return f"до {_fmt(pay_to)} {cur_sign}"
    return "Не указана"


def _get_snippet(item: dict) -> str:
    parts: list[str] = []
    cand = item.get("candidat")
    if cand:
        parts.append(cand)
    work = item.get("work")
    if work:
        parts.append(work)

    text = " | ".join(p.strip() for p in parts if p)
    # Убираем HTML-разметку и управляющие переносы
    text = text.replace("<br/>", " ").replace("<br>", " ").replace("\n", " ")
    if len(text) > 300:
        text = text[:297] + "..."
    return text
