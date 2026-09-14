"""
sources.py — реестр источников вакансий.

Задача: дать единый интерфейс для нескольких площадок (hh, superjob, ...),
чтобы дальше можно было легко добавлять новые.

Каждый источник должен реализовывать:
  - fetch_vacancies() -> list[dict]
  - format_vacancy_message(vacancy: dict) -> str
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


FetchFn = Callable[[], Awaitable[list[dict]]]
FormatFn = Callable[[dict], str]


@dataclass(frozen=True)
class Source:
    name: str
    fetch: FetchFn
    format_message: FormatFn


def get_sources() -> dict[str, Source]:
    # Импорты внутри, чтобы не тянуть лишние зависимости при старте.
    from parser import fetch_vacancies as hh_fetch
    from parser import format_vacancy_message as hh_format
    from parser_superjob import (
        fetch_vacancies as sj_fetch,
        format_vacancy_message as sj_format,
    )
    from parser_trudvsem import (
        fetch_vacancies as tv_fetch,
        format_vacancy_message as tv_format,
    )

    return {
        "hh": Source(name="hh", fetch=hh_fetch, format_message=hh_format),
        "superjob": Source(
            name="superjob", fetch=sj_fetch, format_message=sj_format
        ),
        "trudvsem": Source(
            name="trudvsem", fetch=tv_fetch, format_message=tv_format
        ),
    }

