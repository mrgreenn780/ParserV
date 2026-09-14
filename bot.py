"""
bot.py — Модуль Telegram-бота на aiogram 3.

Отвечает за:
  - Обработку команд /start, /stop, /help, /status
  - Рассылку новых вакансий всем подписчикам
"""

import asyncio
import socket
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramForbiddenError

from config import BOT_TOKEN
from database import (
    add_subscriber,
    remove_subscriber,
    get_all_subscribers,
    get_subscriber_count,
    ensure_default_sources,
    has_any_source_settings,
    get_user_sources,
    set_user_source_enabled,
)
from aggregator import fetch_vacancies_for_sources_detailed, format_vacancy_message
from sources import get_sources

# ─── Инициализация бота ─────────────────────────────────────────────────

def _make_telegram_session() -> AiohttpSession:
    """
    Windows иногда «подвисает» на IPv6/HappyEyeballs при коннекте к api.telegram.org.
    Принудительно используем IPv4 для стабильности.
    """
    session = AiohttpSession()
    # Небольшой хак: AiohttpSession строит TCPConnector из self._connector_init
    # (см. aiogram.client.session.aiohttp.AiohttpSession).
    session._connector_init["family"] = socket.AF_INET
    # Чуть увеличим общий таймаут рукопожатия/запроса
    session._connector_init["ssl"] = session._connector_init.get("ssl")
    return session


# Создаём объект бота с HTML-разметкой по умолчанию
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=_make_telegram_session(),
)

# Dispatcher — «мозг» бота, который распределяет сообщения по обработчикам
dp = Dispatcher()

# Router — маршрутизатор для наших обработчиков команд
router = Router(name="main_router")
dp.include_router(router)


# ─── Обработчики команд ─────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    Обработчик команды /start.
    Подписывает пользователя на рассылку вакансий.
    """
    user_id = message.from_user.id
    username = message.from_user.username

    is_new = add_subscriber(user_id, username)
    # Дефолт только для новых пользователей без настроек источников.
    if not has_any_source_settings(user_id):
        ensure_default_sources(user_id, sources=["hh"])

    if is_new:
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Вы подписались на рассылку новых вакансий "
            "<b>менеджера маркетплейсов (OZON / Wildberries)</b>.\n\n"
            "Вы можете выбрать, из каких источников получать вакансии.\n"
            "Откройте меню источников: /sources\n\n"
            "📌 Команды:\n"
            "/stop — отписаться от рассылки\n"
            "/status — сколько подписчиков\n"
            "/sources — выбрать источники\n"
            "/help — справка"
        )
    else:
        await message.answer(
            "✅ Вы уже подписаны на рассылку!\n\n"
            "Я продолжаю следить за новыми вакансиями для вас. "
            "Напишите /stop, чтобы отписаться."
        )


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    """
    Обработчик команды /stop.
    Отписывает пользователя от рассылки.
    """
    user_id = message.from_user.id
    removed = remove_subscriber(user_id)

    if removed:
        await message.answer(
            "😔 Вы отписались от рассылки вакансий.\n\n"
            "Если захотите вернуться — просто нажмите /start."
        )
    else:
        await message.answer(
            "🤔 Вы и так не подписаны на рассылку.\n"
            "Нажмите /start, чтобы подписаться."
        )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Обработчик команды /help — выводит справку."""
    await message.answer(
        "ℹ️ <b>Бот мониторинга вакансий</b>\n\n"
        "Этот бот автоматически ищет свежие вакансии "
        "<b>менеджера маркетплейсов</b> (OZON, Wildberries) "
        "и присылает их вам из выбранных источников.\n\n"
        "📌 <b>Команды:</b>\n"
        "/start — подписаться на рассылку\n"
        "/stop — отписаться\n"
        "/status — количество подписчиков\n"
        "/sources — выбрать источники\n"
        "/check — ручная проверка новых вакансий\n"
        "/help — эта справка\n\n"
        "🔄 Проверка новых вакансий происходит каждые 15 минут."
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Обработчик команды /status — показывает статистику."""
    count = get_subscriber_count()
    await message.answer(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Подписчиков: <b>{count}</b>"
    )


@router.message(Command("check"))
async def cmd_check(message: Message) -> None:
    """
    Ручная проверка источника вакансий (для отладки).
    Пишет результат только пользователю, вызвавшему команду.
    """
    await message.answer("🔎 Проверяю источники... (пару секунд)")
    try:
        sources = get_sources()
        if not has_any_source_settings(message.from_user.id):
            ensure_default_sources(message.from_user.id, sources=["hh"])
        states = get_user_sources(message.from_user.id)
        enabled = [s for s, on in states.items() if on and s in sources]
        if not enabled:
            await message.answer(
                "У тебя не включён ни один источник.\n"
                "Открой /sources и включи нужные."
            )
            return
        vacancies, errors = await fetch_vacancies_for_sources_detailed(enabled)
    except PermissionError as e:
        await message.answer(
            "⛔️ Источник отклонил запрос (доступ/ключ/блокировка).\n\n"
            f"Детали: <code>{str(e)[:300]}</code>"
        )
        return
    except Exception as e:
        await message.answer(f"⚠️ Ошибка при запросе: <code>{e!r}</code>")
        return

    if not vacancies:
        if errors:
            lines = [
                "Новых вакансий не найдено, но при опросе источников были ошибки:",
                "",
            ]
            for name in sorted(errors.keys()):
                lines.append(f"• <b>{name}</b>: <code>{errors[name][:250]}</code>")
            lines.append("")
            lines.append(
                "Если это SuperJob — проверь <code>SUPERJOB_API_KEY</code> в .env.\n"
                "Если это trudvsem — у них API иногда отвечает 502, попробуй позже."
            )
            await message.answer("\n".join(lines))
        else:
            await message.answer(
                "Новых вакансий не найдено (или всё уже отправлялось)."
            )
        return

    await message.answer(
        f"Найдено новых вакансий: <b>{len(vacancies)}</b>. Отправляю первые 3."
    )
    for v in vacancies[:3]:
        await message.answer(format_vacancy_message(v))
        await asyncio.sleep(0.2)


@router.message(Command("sources"))
async def cmd_sources(message: Message) -> None:
    """Меню выбора источников вакансий для пользователя."""
    user_id = message.from_user.id
    sources = get_sources()
    if not has_any_source_settings(user_id):
        ensure_default_sources(user_id, sources=["hh"])

    states = get_user_sources(user_id)
    kb = _build_sources_keyboard(sources=list(sources.keys()), states=states)
    await message.answer("Выберите источники вакансий:", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("src:"))
async def cb_toggle_source(callback) -> None:
    user_id = callback.from_user.id
    source = callback.data.split(":", 1)[1]
    sources = get_sources()
    if source not in sources:
        await callback.answer("Неизвестный источник.", show_alert=True)
        return

    states = get_user_sources(user_id)
    current = bool(states.get(source, False))
    set_user_source_enabled(user_id, source, not current)
    states = get_user_sources(user_id)
    kb = _build_sources_keyboard(sources=list(sources.keys()), states=states)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer("Готово")


def _build_sources_keyboard(*, sources: list[str], states: dict[str, bool]):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for s in sorted(sources):
        on = bool(states.get(s, False))
        label = f"{'✅' if on else '⬜️'} {s}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"src:{s}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Функция рассылки ───────────────────────────────────────────────────

async def broadcast_to_subscribers(text: str, *, user_ids: list[int] | None = None) -> int:
    """
    Отправляет сообщение ВСЕМ подписчикам.

    Возвращает количество успешно отправленных сообщений.
    Если пользователь заблокировал бота, ошибка игнорируется.
    """
    subscribers = user_ids if user_ids is not None else get_all_subscribers()
    success_count = 0

    for user_id in subscribers:
        try:
            await bot.send_message(chat_id=user_id, text=text)
            success_count += 1
            # Пауза 0.05 сек между сообщениями, чтобы не превысить
            # лимит Telegram API (30 сообщений в секунду)
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            # Пользователь заблокировал бота / удалил чат.
            remove_subscriber(user_id)
            print(f"[BOT] Пользователь {user_id} заблокировал бота — удалён из базы.")
        except Exception as e:
            print(f"[BOT] Не удалось отправить пользователю {user_id}: {e!r}")

    return success_count
