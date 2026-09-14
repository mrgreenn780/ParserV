"""
parser_hh_via_ssh.py — парсер вакансий hh.ru через SSH-канал на зарубежный VPS.

Почему так:
    Из РФ `api.hh.ru/vacancies` жёстко блокирует anonymous-запросы (403),
    а страница `hh.ru/search/vacancy` отдаёт "isLightPage" без данных.
    С зарубежного IP (наш VPS в Финляндии) та же страница отдаёт полноценный
    HTML с встроенным JSON "HH-Lux-InitialState", где лежат все вакансии.

    Через paramiko открываем SSH-сессию, выполняем curl на VPS,
    получаем HTML, вытаскиваем и парсим JSON локально.

Настройки берутся из .env:
    HH_SSH_HOST     — IP/hostname VPS
    HH_SSH_USER     — логин (обычно root)
    HH_SSH_KEY_PATH — путь к приватному SSH-ключу
    HH_SEARCH_QUERY — поисковая строка

Одно SSH-соединение переиспользуется между вызовами fetch_vacancies;
если оно обрывается — при следующем вызове будет установлено заново.
"""

from __future__ import annotations

import asyncio
import html as html_module
import json
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any

import paramiko

from config import (
    HH_SEARCH_QUERY,
    HH_SSH_HOST,
    HH_SSH_USER,
    HH_SSH_KEY_PATH,
    HH_USER_AGENT,
)
from database import is_vacancy_seen


# ─── SSH-соединение (ленивое + переиспользуемое) ────────────────────────────

_ssh_lock = threading.Lock()
_ssh_client: paramiko.SSHClient | None = None


def _load_key(path: str) -> paramiko.PKey:
    """Пытаемся распознать формат ключа автоматически."""
    p = Path(path).expanduser()
    last_err: Exception | None = None
    key_classes = []
    for name in ("Ed25519Key", "ECDSAKey", "RSAKey", "DSSKey"):
        cls = getattr(paramiko, name, None)
        if cls is not None:
            key_classes.append(cls)
    for cls in key_classes:
        try:
            return cls.from_private_key_file(str(p))
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Не удалось прочитать ключ {p}: {last_err!r}")


def _get_client() -> paramiko.SSHClient:
    """Возвращает живое SSH-соединение (ленивое создание / переподключение)."""
    global _ssh_client
    with _ssh_lock:
        if _ssh_client is not None:
            transport = _ssh_client.get_transport()
            if transport is not None and transport.is_active():
                return _ssh_client
            try:
                _ssh_client.close()
            except Exception:
                pass
            _ssh_client = None

        if not (HH_SSH_HOST and HH_SSH_USER and HH_SSH_KEY_PATH):
            raise PermissionError(
                "SSH-доступ к VPS не настроен. Пропиши в .env: "
                "HH_SSH_HOST, HH_SSH_USER, HH_SSH_KEY_PATH."
            )

        pkey = _load_key(HH_SSH_KEY_PATH)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=HH_SSH_HOST,
            username=HH_SSH_USER,
            pkey=pkey,
            timeout=20,
            banner_timeout=20,
            auth_timeout=20,
            allow_agent=False,
            look_for_keys=False,
        )
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
        _ssh_client = client
        return client


def _ssh_exec(cmd: str, timeout: int = 60) -> tuple[int, bytes, bytes]:
    client = _get_client()
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    return rc, stdout.read(), stderr.read()


# ─── HTTP через SSH ─────────────────────────────────────────────────────────

_MARKER = "\n@@HTTP_CODE@@"
_MARKER_RE = re.compile(r"@@HTTP_CODE@@(\d{3})\s*$")


def _fetch_html_via_ssh(url: str) -> tuple[int, str]:
    """
    Выполняет curl на VPS и возвращает (http_code, html).
    HTTP_CODE мы добавляем в конец stdout через curl's -w.
    """

    escaped_url = url.replace("'", "'\"'\"'")
    escaped_ua = HH_USER_AGENT.replace("'", "'\"'\"'")
    cmd = (
        "curl -sS -L "
        f"-H 'User-Agent: {escaped_ua}' "
        "-H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' "
        "-H 'Accept-Language: ru-RU,ru;q=0.9,en;q=0.8' "
        "--compressed "
        f"'{escaped_url}' --max-time 40 "
        f"-w '{_MARKER}%{{http_code}}'"
    )
    rc, stdout_b, stderr_b = _ssh_exec(cmd, timeout=60)

    body = stdout_b.decode("utf-8", errors="replace")
    m = _MARKER_RE.search(body)
    if not m:
        err_msg = stderr_b.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"SSH curl failed (rc={rc}): {err_msg or 'no marker in stdout'}"
        )
    http_code = int(m.group(1))
    body = body[: m.start()]
    return http_code, body


# ─── Парсинг JSON из HTML ───────────────────────────────────────────────────

_TEMPLATE_RE = re.compile(
    r'<template[^>]*id="HH-Lux-InitialState"[^>]*>(.*?)</template>',
    re.DOTALL,
)


def _extract_state(html: str) -> dict[str, Any]:
    m = _TEMPLATE_RE.search(html)
    if not m:
        raise RuntimeError("HH-Lux-InitialState не найден в HTML (структура страницы изменилась?).")
    raw = html_module.unescape(m.group(1)).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Не удалось распарсить JSON HH-Lux-InitialState: {e}")


def _extract_vacancies_list(state: dict[str, Any]) -> list[dict[str, Any]]:
    # Стандартный путь
    result = state.get("vacancySearchResult") or {}
    vacancies = result.get("vacancies")
    if isinstance(vacancies, list):
        return vacancies

    # Фолбэк: ищем произвольно
    from collections import deque

    q: deque[tuple[Any, tuple[str, ...]]] = deque([(state, ())])
    while q:
        node, path = q.popleft()
        if len(path) > 5:
            continue
        if isinstance(node, dict):
            for k, v in node.items():
                if (
                    isinstance(v, list)
                    and v
                    and isinstance(v[0], dict)
                    and "vacancyId" in v[0]
                ):
                    return v
                q.append((v, path + (k,)))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                q.append((v, path + (f"[{i}]",)))
    return []


# ─── Публичный API модуля ───────────────────────────────────────────────────

async def fetch_vacancies() -> list[dict]:
    """
    Забирает свежие вакансии с hh.ru через SSH-канал.
    Возвращает только НОВЫЕ (которых нет в БД).
    """

    def _sync() -> list[dict]:
        qs = urllib.parse.urlencode({
            "text": HH_SEARCH_QUERY,
            "items_on_page": 50,
            "order_by": "publication_time",
            "search_period": 1,
        })
        url = f"https://hh.ru/search/vacancy?{qs}"

        http_code, html = _fetch_html_via_ssh(url)
        print(f"[HH/SSH] GET {url[:90]}... -> HTTP {http_code}, {len(html)} bytes")

        if http_code == 403:
            raise PermissionError(
                f"hh.ru вернул 403 даже с VPS ({HH_SSH_HOST}). Возможно, IP VPS попал в бан-лист."
            )
        if http_code != 200:
            raise RuntimeError(f"hh.ru вернул HTTP {http_code}")

        state = _extract_state(html)
        items = _extract_vacancies_list(state)
        print(f"[HH/SSH] Всего вакансий в выдаче: {len(items)}")

        new_vacancies: list[dict] = []
        for item in items:
            vid = item.get("vacancyId")
            if vid is None:
                continue
            vacancy_id = f"hh:{vid}"
            if is_vacancy_seen(vacancy_id):
                continue
            new_vacancies.append(_normalize(item, vacancy_id))
        print(f"[HH/SSH] Из них новых: {len(new_vacancies)}")
        return new_vacancies

    try:
        return await asyncio.to_thread(_sync)
    except PermissionError:
        raise
    except paramiko.SSHException as e:
        # закрываем сломанное соединение, чтобы в следующий раз переподключиться
        _close_client()
        raise RuntimeError(f"SSH ошибка: {e!r}") from e
    except Exception:
        raise


def _close_client() -> None:
    global _ssh_client
    with _ssh_lock:
        if _ssh_client is not None:
            try:
                _ssh_client.close()
            except Exception:
                pass
            _ssh_client = None


# ─── Маппинг одной вакансии в нашу структуру ────────────────────────────────

def _normalize(item: dict[str, Any], vacancy_id: str) -> dict:
    title = item.get("name") or "Без названия"
    area = (item.get("area") or {}).get("name") or "—"
    company = item.get("company") or {}
    employer = company.get("visibleName") or company.get("name") or "—"

    url = (item.get("links") or {}).get("desktop") or f"https://hh.ru/vacancy/{item.get('vacancyId')}"

    salary = _format_salary(item.get("compensation"))

    return {
        "id": vacancy_id,
        "title": title,
        "employer": employer,
        "salary": salary,
        "url": url,
        "area": area,
        "snippet": "",  # сниппет требует отдельного запроса — оставляем пустым
    }


def _format_salary(comp: dict[str, Any] | None) -> str:
    if not comp:
        return "Не указана"
    cur = (comp.get("currencyCode") or "RUR").upper()
    cur_map = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€", "KZT": "₸", "BYR": "Br", "UAH": "₴"}
    sign = cur_map.get(cur, cur)
    pay_from = comp.get("from")
    pay_to = comp.get("to")

    def _f(v: int) -> str:
        return f"{int(v):,}".replace(",", " ")

    if pay_from and pay_to:
        return f"{_f(pay_from)} – {_f(pay_to)} {sign}"
    if pay_from:
        return f"от {_f(pay_from)} {sign}"
    if pay_to:
        return f"до {_f(pay_to)} {sign}"
    return "Не указана"


def format_vacancy_message(vacancy: dict) -> str:
    lines = [
        f"🔥 <b>{vacancy['title']}</b>",
        f"🏢 {vacancy['employer']}",
        f"📍 {vacancy['area']}",
        f"💰 {vacancy['salary']}",
    ]
    if vacancy.get("snippet"):
        lines.append(f"\n📋 <i>{vacancy['snippet']}</i>")
    lines.append(f"\n🔗 <a href=\"{vacancy['url']}\">Открыть вакансию</a>")
    return "\n".join(lines)
