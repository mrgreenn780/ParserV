"""
parser_hh.py — Модуль парсинга вакансий с HeadHunter (hh.ru).

Использует открытое API hh.ru для поиска вакансий.
Документация API: https://api.hh.ru/openapi/redoc

Ключевая логика:
  1. Отправляем GET-запрос к API с поисковым запросом.
  2. Получаем JSON со списком вакансий.
  3. Фильтруем только те, которых ещё нет в нашей базе данных.
  4. Возвращаем список новых вакансий для рассылки.
"""

import aiohttp
from database import is_vacancy_seen
from config import HH_SEARCH_QUERY, HH_USER_AGENT


# Базовый URL API HeadHunter
HH_API_URL = "https://api.hh.ru/vacancies"


async def fetch_vacancies() -> list[dict]:
    """
    Запрашивает свежие вакансии с hh.ru и возвращает
    только НОВЫЕ (которых ещё нет в нашей базе).

    Каждая вакансия в списке — это словарь с ключами:
      - id:        str   — ID вакансии
      - title:     str   — Название
      - employer:  str   — Работодатель
      - salary:    str   — Зарплата (или "Не указана")
      - url:       str   — Ссылка на вакансию
      - area:      str   — Город
      - snippet:   str   — Краткие требования
    """

    # Параметры запроса к API
    params = {
        "text": HH_SEARCH_QUERY,       # Поисковый запрос
        "period": 1,                    # Только за последние сутки
        "per_page": 50,                 # До 50 вакансий за раз
        "page": 0,                      # Первая страница результатов
        "order_by": "publication_time", # Сначала самые свежие
    }

    # Заголовок User-Agent обязателен для API hh.ru
    headers = {
        "User-Agent": HH_USER_AGENT,
        "Accept": "application/json",
    }

    new_vacancies: list[dict] = []

    try:
        # Создаём асинхронную HTTP-сессию
        async with aiohttp.ClientSession() as session:
            async with session.get(
                HH_API_URL, params=params, headers=headers
            ) as response:

                # Проверяем что запрос прошёл успешно (код 200)
                if response.status != 200:
                    body_preview = (await response.text())[:500]
                    # 400 bad_user_agent / 403 forbidden (ddos-guard) встречаются чаще всего
                    if response.status == 403:
                        raise PermissionError(
                            f"hh API forbidden (403): {body_preview}"
                        )
                    raise RuntimeError(
                        f"hh API error {response.status}: {body_preview}"
                    )

                data = await response.json()

        # data["items"] — это список вакансий
        items = data.get("items", [])
        print(f"[HH] Получено {len(items)} вакансий с hh.ru")

        for item in items:
            vacancy_id = str(item["id"])

            # Проверяем: видели мы уже эту вакансию или нет?
            if is_vacancy_seen(vacancy_id):
                continue  # Уже отправляли — пропускаем

            # Формируем удобную структуру данных
            vacancy = {
                "id": vacancy_id,
                "title": item.get("name", "Без названия"),
                "employer": _get_employer(item),
                "salary": _format_salary(item.get("salary")),
                "url": item.get("alternate_url", ""),
                "area": item.get("area", {}).get("name", "—"),
                "snippet": _get_snippet(item),
            }

            new_vacancies.append(vacancy)

        print(f"[HH] Из них новых: {len(new_vacancies)}")

    except aiohttp.ClientError as e:
        print(f"[HH] Ошибка сети: {e}")
    except PermissionError:
        raise
    except Exception as e:
        print(f"[HH] Непредвиденная ошибка: {e!r}")

    return new_vacancies


def format_vacancy_message(vacancy: dict) -> str:
    """
    Форматирует вакансию в красивое Telegram-сообщение
    с использованием HTML-разметки.
    """
    lines = [
        f"🔥 <b>{vacancy['title']}</b>",
        f"🏢 {vacancy['employer']}",
        f"📍 {vacancy['area']}",
        f"💰 {vacancy['salary']}",
    ]

    if vacancy["snippet"]:
        lines.append(f"\n📋 <i>{vacancy['snippet']}</i>")

    lines.append(f"\n🔗 <a href=\"{vacancy['url']}\">Открыть вакансию</a>")

    return "\n".join(lines)


# ─── Вспомогательные функции ────────────────────────────────────────────

def _get_employer(item: dict) -> str:
    """Извлекает имя работодателя из ответа API."""
    employer = item.get("employer")
    if employer:
        return employer.get("name", "Не указан")
    return "Не указан"


def _format_salary(salary: dict | None) -> str:
    """
    Форматирует зарплату в человекочитаемую строку.
    Примеры: "от 50 000 ₽", "80 000 – 120 000 ₽", "Не указана".
    """
    if salary is None:
        return "Не указана"

    currency_map = {"RUR": "₽", "USD": "$", "EUR": "€", "KZT": "₸"}
    cur = currency_map.get(salary.get("currency", ""), salary.get("currency", ""))

    from_val = salary.get("from")
    to_val = salary.get("to")

    if from_val and to_val:
        return f"{from_val:,} – {to_val:,} {cur}".replace(",", " ")
    elif from_val:
        return f"от {from_val:,} {cur}".replace(",", " ")
    elif to_val:
        return f"до {to_val:,} {cur}".replace(",", " ")
    else:
        return "Не указана"


def _get_snippet(item: dict) -> str:
    """Извлекает краткое описание требований из snippet."""
    snippet = item.get("snippet", {})
    if not snippet:
        return ""

    parts = []
    req = snippet.get("requirement")
    resp = snippet.get("responsibility")

    if req:
        # Убираем HTML-теги подсветки (<highlighttext>)
        req = req.replace("<highlighttext>", "").replace("</highlighttext>", "")
        parts.append(req)
    if resp:
        resp = resp.replace("<highlighttext>", "").replace("</highlighttext>", "")
        parts.append(resp)

    # Ограничиваем длину, чтобы сообщение не было слишком большим
    text = " | ".join(parts)
    if len(text) > 300:
        text = text[:297] + "..."
    return text
