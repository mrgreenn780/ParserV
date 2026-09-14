"""
main.py — Главная точка входа. Запускает всё вместе.

Что делает этот файл:
  1. Инициализирует базу данных (создаёт таблицы, если их нет).
  2. Запускает Telegram-бота (он слушает команды пользователей).
  3. Запускает фоновую задачу-планировщик, которая каждые N минут
     вызывает парсер hh.ru и рассылает новые вакансии подписчикам.

Для запуска:
  python main.py
"""

import asyncio
import sys
from database import init_db, mark_vacancy_seen
from config import CHECK_INTERVAL_MINUTES, BOT_TOKEN, SUPERJOB_API_KEY
from bot import dp, bot, broadcast_to_subscribers
from aggregator import fetch_vacancies_for_sources, format_vacancy_message
from sources import get_sources
from database import get_subscribers_for_source
from aiogram.exceptions import TelegramNetworkError


def _configure_utf8_console() -> None:
    """
    Windows PowerShell/CMD can default to a non-UTF8 codepage.
    This makes `print()` crash on Cyrillic/box-drawing characters.
    """
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # If reconfigure isn't available or fails, keep going.
        pass


async def scheduled_parser() -> None:
    """
    Фоновая задача: каждые CHECK_INTERVAL_MINUTES минут
    запрашивает новые вакансии и рассылает их подписчикам.
    """
    print(f"[SCHEDULER] Парсер будет запускаться каждые {CHECK_INTERVAL_MINUTES} мин.")

    # Ждём 10 секунд перед первым запуском, чтобы бот успел запуститься
    await asyncio.sleep(10)

    while True:
        try:
            print("\n[SCHEDULER] --- Запуск проверки вакансий ---")

            sources = get_sources()
            any_sent = 0

            for source_name in sorted(sources.keys()):
                # 1) Берём подписчиков, которые включили этот источник.
                # Если подписчиков нет — не делаем сетевые запросы вообще.
                user_ids = get_subscribers_for_source(source_name)
                if not user_ids:
                    print(f"[SCHEDULER] Источник {source_name}: подписчиков нет — пропуск.")
                    continue

                if source_name == "superjob" and not SUPERJOB_API_KEY.strip():
                    print(
                        "[SCHEDULER] Источник superjob: SUPERJOB_API_KEY не задан — пропуск "
                        "(включи ключ в .env или выключи источник в /sources)."
                    )
                    continue

                # 2) Получаем новые вакансии от источника
                new_vacancies = await fetch_vacancies_for_sources([source_name])
                if not new_vacancies:
                    continue

                print(
                    f"[SCHEDULER] Источник {source_name}: "
                    f"{len(new_vacancies)} новых вакансий. Рассылаем!"
                )

                for vacancy in new_vacancies:
                    message_text = format_vacancy_message(vacancy)
                    sent = await broadcast_to_subscribers(message_text, user_ids=user_ids)
                    any_sent += sent
                    print(
                        f"  -> [{source_name}] «{vacancy['title']}» — отправлено {sent} подписчикам"
                    )

                    if sent > 0:
                        mark_vacancy_seen(vacancy["id"], vacancy["title"])

                    await asyncio.sleep(1)

            if any_sent == 0:
                print("[SCHEDULER] Новых вакансий нет (или нет подписчиков по источникам).")

        except PermissionError as e:
            # Проблема авторизации к API (нет ключа, блокировка и т.п.).
            backoff_minutes = max(CHECK_INTERVAL_MINUTES, 15)
            print(
                f"[SCHEDULER] Доступ к API не разрешён: {e}. "
                f"Бекофф {backoff_minutes} мин."
            )
            await asyncio.sleep(backoff_minutes * 60)
            continue
        except Exception as e:
            print(f"[SCHEDULER] Ошибка в цикле парсера: {e!r}")

        # Ждём до следующей проверки
        print(f"[SCHEDULER] Следующая проверка через {CHECK_INTERVAL_MINUTES} мин.\n")
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


async def main() -> None:
    """Главная асинхронная функция — запускает бота и планировщик."""

    _configure_utf8_console()

    # Проверяем, что токен настроен
    if not BOT_TOKEN or BOT_TOKEN == "123456789:ABCdefGHIjklMNOpqrsTUVwxyz":
        print("=" * 60)
        print("❌ ОШИБКА: Токен бота не настроен!")
        print()
        print("1. Скопируйте .env.example в .env:")
        print("   copy .env.example .env")
        print()
        print("2. Откройте .env и вставьте токен от @BotFather")
        print("=" * 60)
        return

    # Инициализируем базу данных
    init_db()

    # Запускаем планировщик парсера как фоновую задачу
    asyncio.create_task(scheduled_parser())

    # Запускаем бота (polling — бот постоянно спрашивает Telegram: «есть новые сообщения?»)
    print("[BOT] Бот запущен! Ожидаю сообщения... (Ctrl+C для остановки)")
    backoff = 2
    try:
        while True:
            try:
                await dp.start_polling(bot)
                return
            except TelegramNetworkError as e:
                # Сеть до Telegram может временно «падать» на Windows/VPN/провайдере.
                print(f"[BOT] Сетевая ошибка Telegram: {e!r}. Повтор через {backoff} сек.")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
