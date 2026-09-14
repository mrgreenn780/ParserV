"""
parser_trudvsem.py — парсер вакансий через API портала «Работа России» (trudvsem.ru).

Документация: https://trudvsem.ru/opendata/api
База API: http://opendata.trudvsem.ru/api/v1/vacancies

Мы используем поиск по тексту и пагинацию (limit/offset).
"""

from __future__ import annotations

import aiohttp

import asyncio

from config import HH_SEARCH_QUERY
from database import is_vacancy_seen


# По документации базовый endpoint — http://opendata.trudvsem.ru/api/v1/vacancies
# HTTPS на практике может отдавать 502, поэтому делаем фолбэк.
_BASES = [
    # По документации базовый endpoint — http://...
    "http://opendata.trudvsem.ru/api/v1/vacancies",
    # Иногда у них работает https, но часто отдаёт gateway ошибки.
    "https://opendata.trudvsem.ru/api/v1/vacancies",
]


async def fetch_vacancies() -> list[dict]:
    params = {
        "text": HH_SEARCH_QUERY,
        "limit": 50,
        "offset": 0,
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "job-parser-bot/1.0",
    }
    timeout = aiohttp.ClientTimeout(total=40)

    last_err: Exception | None = None
    data = None

    # Ретраи + переключение base URL. Их API бывает нестабильным (502/503/504).
    for base in _BASES:
        for attempt in range(4):
            try:
                async with aiohttp.ClientSession(
                    timeout=timeout, headers=headers
                ) as session:
                    async with session.get(
                        base, params=params, allow_redirects=True
                    ) as resp:
                        body = await resp.text()
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            break
                        if resp.status in (502, 503, 504, 429):
                            raise RuntimeError(
                                f"gateway {resp.status}: {body[:200]}"
                            )
                        raise RuntimeError(
                            f"trudvsem API HTTP {resp.status}: {body[:300]}"
                        )
            except Exception as e:
                last_err = e
                # эксп. бэкофф: 0.5, 1, 2, 4 сек
                await asyncio.sleep(0.5 * (2**attempt))
                continue
        if data is not None:
            break

    if data is None:
        raise RuntimeError(f"trudvsem API failed: {last_err!r}")

    # Структура бывает разная, поэтому достаем максимально терпимо.
    results = data.get("results") or data.get("result") or data
    vac_container = (
        (results.get("vacancies") if isinstance(results, dict) else None) or {}
    )

    items = None
    if isinstance(vac_container, list):
        items = vac_container
    elif isinstance(vac_container, dict):
        items = (
            vac_container.get("vacancy")
            or vac_container.get("vacancies")
            or vac_container.get("items")
        )

    if not isinstance(items, list):
        items = []

    new_vacancies: list[dict] = []
    for raw in items:
        vac = raw.get("vacancy") if isinstance(raw, dict) and "vacancy" in raw else raw
        if not isinstance(vac, dict):
            continue

        vid = (
            vac.get("vacancy_id")
            or vac.get("vacancyId")
            or vac.get("id")
            or vac.get("vacancy_id_external")
        )
        if vid is None:
            continue

        vacancy_id = f"tv:{vid}"
        if is_vacancy_seen(vacancy_id):
            continue

        title = vac.get("job-name") or vac.get("jobName") or vac.get("profession") or vac.get("name") or "Без названия"
        company = (
            vac.get("company")
            or vac.get("companyName")
            or (vac.get("company") or {}).get("name")
            or vac.get("employer")
            or "—"
        )
        salary = _format_salary(vac)
        area = (
            (vac.get("region") or {}).get("name")
            or (vac.get("region") or {}).get("regionName")
            or vac.get("regionName")
            or "—"
        )
        url = (
            vac.get("vac_url")
            or vac.get("vacancyUrl")
            or vac.get("link")
            or ""
        )

        new_vacancies.append(
            {
                "id": vacancy_id,
                "title": str(title),
                "employer": str(company),
                "salary": salary,
                "area": str(area),
                "url": str(url),
                "snippet": "",
                "source": "trudvsem",
            }
        )

    return new_vacancies


def _format_salary(vac: dict) -> str:
    # По документации бывает salary / salary_min/salary_max / wage...
    for k in ("salary", "wage", "salaryMin", "salaryMax", "salary_min", "salary_max"):
        if k in vac and vac.get(k):
            pass

    mn = vac.get("salary_min") or vac.get("salaryMin") or vac.get("minSalary")
    mx = vac.get("salary_max") or vac.get("salaryMax") or vac.get("maxSalary")
    cur = (vac.get("currency") or vac.get("currencyCode") or "RUR").upper()
    cur_map = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸"}
    sign = cur_map.get(cur, cur)

    def _f(v: int | float) -> str:
        try:
            return f"{int(float(v)):,}".replace(",", " ")
        except Exception:
            return str(v)

    if mn and mx:
        return f"{_f(mn)} – {_f(mx)} {sign}"
    if mn:
        return f"от {_f(mn)} {sign}"
    if mx:
        return f"до {_f(mx)} {sign}"

    s = vac.get("salary") or vac.get("wage")
    if s:
        return f"{s} {sign}".strip()
    return "Не указана"


def format_vacancy_message(vacancy: dict) -> str:
    lines = [
        f"🔥 <b>{vacancy['title']}</b>",
        f"🏢 {vacancy['employer']}",
        f"📍 {vacancy['area']}",
        f"💰 {vacancy['salary']}",
    ]
    if vacancy.get("url"):
        lines.append(f"\n🔗 <a href=\"{vacancy['url']}\">Открыть вакансию</a>")
    return "\n".join(lines)


__all__ = ["fetch_vacancies", "format_vacancy_message"]

