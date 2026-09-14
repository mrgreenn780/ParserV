"""
aggregator.py — агрегатор нескольких источников вакансий.

Возвращает единый список вакансий, но сохраняет в каждой записи поле `source`.
"""

from __future__ import annotations

import asyncio

from sources import get_sources


async def fetch_vacancies_for_sources_detailed(
    enabled: list[str],
) -> tuple[list[dict], dict[str, str]]:
    """
    Возвращает (вакансии, ошибки_по_источникам).

    Ошибки — человекочитаемые строки (для /check), без падения всего агрегатора.
    """
    sources = get_sources()
    enabled = [s for s in enabled if s in sources]
    if not enabled:
        raise RuntimeError(
            "Список источников пуст или содержит неизвестные источники. "
            f"Доступно: {', '.join(sorted(sources.keys()))}"
        )

    async def _one(name: str) -> list[dict]:
        src = sources[name]
        items = await src.fetch()
        for v in items:
            v.setdefault("source", src.name)
        return items

    results = await asyncio.gather(
        *[_one(name) for name in enabled],
        return_exceptions=True,
    )

    merged: list[dict] = []
    errors: dict[str, str] = {}
    for name, part in zip(enabled, results, strict=True):
        if isinstance(part, Exception):
            errors[name] = f"{type(part).__name__}: {part}"
            continue
        merged.extend(part)
    return merged, errors


async def fetch_vacancies_for_sources(enabled: list[str]) -> list[dict]:
    """Совместимость: только список вакансий (ошибки пишутся в лог)."""
    items, errors = await fetch_vacancies_for_sources_detailed(enabled)
    if errors:
        for name, msg in errors.items():
            print(f"[AGG] Источник {name} упал: {msg}")
    return items


def format_vacancy_message(vacancy: dict) -> str:
    sources = get_sources()
    src_name = (vacancy.get("source") or "").strip().lower()
    src = sources.get(src_name)
    if src is None:
        # fallback: hh формат по умолчанию
        src = sources["hh"]
    return src.format_message(vacancy)
