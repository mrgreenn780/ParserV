"""
database.py — Модуль работы с базой данных SQLite.

Отвечает за:
  - Создание таблиц при первом запуске.
  - Добавление / удаление подписчиков (пользователей бота).
  - Сохранение ID уже отправленных вакансий, чтобы не дублировать.
"""

import sqlite3
from config import DATABASE_PATH


def get_connection() -> sqlite3.Connection:
    """Создаёт и возвращает соединение с базой данных."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # позволяет обращаться к полям по имени
    return conn


def init_db() -> None:
    """
    Создаёт таблицы, если они ещё не существуют.
    Вызывается один раз при старте бота.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Таблица подписчиков
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id   INTEGER PRIMARY KEY,   -- Telegram user ID
            username  TEXT,                   -- @username (может быть пустым)
            joined_at TEXT DEFAULT (datetime('now'))  -- когда подписался
        )
    """)

    # Таблица уже отправленных вакансий
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_vacancies (
            vacancy_id TEXT PRIMARY KEY,      -- ID вакансии на hh.ru
            title      TEXT,                  -- Название вакансии
            added_at   TEXT DEFAULT (datetime('now'))  -- когда добавили
        )
    """)

    # Таблица выбора источников по подписчикам
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriber_sources (
            user_id INTEGER NOT NULL,
            source  TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, source),
            FOREIGN KEY (user_id) REFERENCES subscribers(user_id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Таблицы инициализированы.")


# ─── Работа с подписчиками ──────────────────────────────────────────────

def add_subscriber(user_id: int, username: str | None = None) -> bool:
    """
    Добавляет подписчика в базу.
    Возвращает True, если подписчик новый; False, если уже был.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO subscribers (user_id, username) VALUES (?, ?)",
            (user_id, username),
        )
        conn.commit()
        return True  # новый подписчик
    except sqlite3.IntegrityError:
        return False  # уже существует
    finally:
        conn.close()


def ensure_default_sources(user_id: int, sources: list[str]) -> None:
    """
    Гарантирует, что у пользователя есть записи по источникам (enabled=1),
    если их ещё нет. Используется при /start и при показе меню.
    """
    conn = get_connection()
    cursor = conn.cursor()
    for s in sources:
        cursor.execute(
            "INSERT OR IGNORE INTO subscriber_sources (user_id, source, enabled) VALUES (?, ?, 1)",
            (user_id, s),
        )
    conn.commit()
    conn.close()


def has_any_source_settings(user_id: int) -> bool:
    """True, если пользователь уже хоть раз настраивал источники."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM subscriber_sources WHERE user_id = ? LIMIT 1",
        (user_id,),
    )
    ok = cursor.fetchone() is not None
    conn.close()
    return ok


def remove_subscriber(user_id: int) -> bool:
    """
    Удаляет подписчика из базы.
    Возвращает True, если подписчик был найден и удалён.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
    removed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return removed


def get_all_subscribers() -> list[int]:
    """Возвращает список Telegram ID всех активных подписчиков."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM subscribers")
    user_ids = [row["user_id"] for row in cursor.fetchall()]
    conn.close()
    return user_ids


def get_subscribers_for_source(source: str) -> list[int]:
    """Подписчики, у которых включён конкретный источник."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id FROM subscriber_sources WHERE source = ? AND enabled = 1",
        (source,),
    )
    user_ids = [row["user_id"] for row in cursor.fetchall()]
    conn.close()
    return user_ids


def get_user_sources(user_id: int) -> dict[str, bool]:
    """Возвращает {source: enabled} для пользователя."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT source, enabled FROM subscriber_sources WHERE user_id = ?",
        (user_id,),
    )
    data = {row["source"]: bool(row["enabled"]) for row in cursor.fetchall()}
    conn.close()
    return data


def set_user_source_enabled(user_id: int, source: str, enabled: bool) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO subscriber_sources (user_id, source, enabled) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, source) DO UPDATE SET enabled = excluded.enabled",
        (user_id, source, 1 if enabled else 0),
    )
    conn.commit()
    conn.close()


def get_subscriber_count() -> int:
    """Возвращает количество подписчиков."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM subscribers")
    count = cursor.fetchone()["cnt"]
    conn.close()
    return count


# ─── Работа с вакансиями ────────────────────────────────────────────────

def is_vacancy_seen(vacancy_id: str) -> bool:
    """Проверяет, отправляли ли мы уже эту вакансию."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM seen_vacancies WHERE vacancy_id = ?", (vacancy_id,)
    )
    result = cursor.fetchone() is not None
    conn.close()
    return result


def mark_vacancy_seen(vacancy_id: str, title: str) -> None:
    """Отмечает вакансию как отправленную (сохраняет в базу)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO seen_vacancies (vacancy_id, title) VALUES (?, ?)",
        (vacancy_id, title),
    )
    conn.commit()
    conn.close()
