from __future__ import annotations

from hashlib import sha256

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from job_bot.domain import Decision, Vacancy
from job_bot.settings import Settings
from job_bot.storage import (
    SourcePreferenceStore,
    VacancyFeedbackStore,
    feedback_external_id_token,
    feedback_source_token,
)
from job_bot.telegram.formatting import format_latest_matches, format_vacancy

_FEEDBACK_PREFIX = "fb"
_SOURCE_PREFIX = "src"
_LATEST_PREFIX = "latest"
_FEEDBACK_LABELS = {"saved": "Сохранено", "rejected": "Не подходит"}
_FEEDBACK_CODES = {"saved": "s", "rejected": "r"}
_FEEDBACK_VALUES = {code: value for value, code in _FEEDBACK_CODES.items()}


def _is_allowed_chat(chat_id: int, settings: Settings) -> bool:
    return (
        settings.telegram_recipient_chat_id is not None
        and chat_id == settings.telegram_recipient_chat_id
    )


def _feedback_data(value: str, source: str, external_id: str) -> str:
    code = _FEEDBACK_CODES[value]
    data = (
        f"{_FEEDBACK_PREFIX}:{code}:{feedback_source_token(source)}:"
        f"{feedback_external_id_token(external_id)}"
    )
    if len(data.encode()) > 64:
        raise ValueError("Telegram callback data exceeds 64 bytes")
    return data


def _parse_feedback_data(data: str) -> tuple[str, str, str] | None:
    parts = data.split(":", 3)
    if len(parts) != 4 or parts[0] != _FEEDBACK_PREFIX or parts[1] not in _FEEDBACK_VALUES:
        return None
    return _FEEDBACK_VALUES[parts[1]], parts[2], parts[3]


def _source_token(source: str) -> str:
    return sha256(source.encode()).hexdigest()[:12]


def _source_map(sources: tuple[str, ...]) -> dict[str, str]:
    result = {_source_token(source): source for source in sources}
    if len(result) != len(sources):
        raise ValueError("Source callback token collision")
    return result


def _sources_text(states: dict[str, bool]) -> str:
    enabled = sum(states.values())
    return (
        "<b>Источники уведомлений</b>\n\n"
        f"Включено: {enabled} из {len(states)}.\n"
        "Нажмите на источник, чтобы включить или отключить его.\n\n"
        "Отключённые источники продолжают пополнять раздел «Последние вакансии», "
        "но уведомления из них не приходят."
    )


def _sources_keyboard(states: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if enabled else '⛔'} {source}",
                callback_data=f"{_SOURCE_PREFIX}:toggle:{_source_token(source)}",
            )
        ]
        for source, enabled in states.items()
    ]
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="✅ Включить все",
                    callback_data=f"{_SOURCE_PREFIX}:all:on",
                ),
                InlineKeyboardButton(
                    text="⛔ Отключить все",
                    callback_data=f"{_SOURCE_PREFIX}:all:off",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🕘 Последние вакансии",
                    callback_data=f"{_LATEST_PREFIX}:menu",
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _latest_keyboard(sources: tuple[str, ...]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=source,
                callback_data=f"{_LATEST_PREFIX}:show:{_source_token(source)}",
            )
        ]
        for source in sources
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="⚙️ Настроить источники",
                callback_data=f"{_SOURCE_PREFIX}:menu",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_dispatcher(
    settings: Settings,
    feedback_store: VacancyFeedbackStore | None = None,
    preference_store: SourcePreferenceStore | None = None,
    source_names: tuple[str, ...] = (),
) -> Dispatcher:
    router = Router(name="commands")
    source_by_token = _source_map(source_names)

    async def show_sources(message: Message) -> None:
        if not _is_allowed_chat(message.chat.id, settings):
            await message.answer("Этот бот является приватным.")
            return
        if preference_store is None:
            await message.answer("Настройки источников временно недоступны.")
            return
        states = await preference_store.source_states(message.chat.id, source_names)
        await message.answer(
            _sources_text(states),
            parse_mode="HTML",
            reply_markup=_sources_keyboard(states),
        )

    async def show_latest(message: Message) -> None:
        if not _is_allowed_chat(message.chat.id, settings):
            await message.answer("Этот бот является приватным.")
            return
        await message.answer(
            "<b>Последние подходящие вакансии</b>\n\nВыберите источник:",
            parse_mode="HTML",
            reply_markup=_latest_keyboard(source_names),
        )

    async def start(message: Message) -> None:
        chat_id = message.chat.id
        if settings.telegram_recipient_chat_id is None:
            await message.answer(
                "Бот запущен.\n\n"
                f"ID этого чата: <code>{chat_id}</code>\n"
                "Запишите его в TELEGRAM_RECIPIENT_CHAT_ID и перезапустите бота.",
                parse_mode="HTML",
            )
            return

        if not _is_allowed_chat(message.chat.id, settings):
            await message.answer("Этот бот является приватным.")
            return

        await message.answer(
            "Бот настроен и готов присылать подходящие вакансии.\n\n"
            "/sources — выбрать источники уведомлений\n"
            "/latest — последние 10 подходящих вакансий по источнику\n"
            "/status — проверить фильтры"
        )

    async def status(message: Message) -> None:
        if not _is_allowed_chat(message.chat.id, settings):
            await message.answer("Этот бот является приватным.")
            return

        await message.answer(
            "✅ Бот работает.\n\n"
            "Фильтры: Project Manager, опыт до 3 лет, английский до B1, "
            "remote из Беларуси или hybrid в Беларуси, зарплата от $1000 "
            "либо не указана."
        )

    async def feedback(callback: CallbackQuery) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение больше недоступно.", show_alert=True)
            return
        if not _is_allowed_chat(callback.message.chat.id, settings):
            await callback.answer("Этот бот является приватным.", show_alert=True)
            return

        if callback.data == "fb:done":
            await callback.answer("Действие уже сохранено.")
            return

        parsed = _parse_feedback_data(callback.data or "")
        if parsed is None or feedback_store is None:
            await callback.answer("Не удалось обработать действие.", show_alert=True)
            return

        value, source, external_id = parsed
        recorded = await feedback_store.record_feedback(source, external_id, value)
        if not recorded:
            await callback.answer("Вакансия не найдена в базе.", show_alert=True)
            return

        label = _FEEDBACK_LABELS[value]
        await callback.answer(label)
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"✅ {label}", callback_data="fb:done")]
                ]
            )
        )

    async def source_callback(callback: CallbackQuery) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение больше недоступно.", show_alert=True)
            return
        chat_id = callback.message.chat.id
        if not _is_allowed_chat(chat_id, settings):
            await callback.answer("Этот бот является приватным.", show_alert=True)
            return
        if preference_store is None:
            await callback.answer("Настройки временно недоступны.", show_alert=True)
            return

        data = callback.data or ""
        parts = data.split(":")
        if data == f"{_SOURCE_PREFIX}:menu":
            pass
        elif len(parts) == 3 and parts[:2] == [_SOURCE_PREFIX, "toggle"]:
            source = source_by_token.get(parts[2])
            if source is None:
                await callback.answer("Источник больше недоступен.", show_alert=True)
                return
            enabled = await preference_store.toggle_source(chat_id, source)
            await callback.answer(
                f"{source}: {'включён' if enabled else 'отключён'}"
            )
        elif data in {f"{_SOURCE_PREFIX}:all:on", f"{_SOURCE_PREFIX}:all:off"}:
            enabled = data.endswith(":on")
            await preference_store.set_sources_enabled(
                chat_id,
                source_names,
                enabled=enabled,
            )
            await callback.answer("Настройки сохранены.")
        else:
            await callback.answer("Неизвестное действие.", show_alert=True)
            return

        states = await preference_store.source_states(chat_id, source_names)
        await callback.message.edit_text(
            _sources_text(states),
            parse_mode="HTML",
            reply_markup=_sources_keyboard(states),
        )

    async def latest_callback(callback: CallbackQuery) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer("Сообщение больше недоступно.", show_alert=True)
            return
        if not _is_allowed_chat(callback.message.chat.id, settings):
            await callback.answer("Этот бот является приватным.", show_alert=True)
            return
        if preference_store is None:
            await callback.answer("История временно недоступна.", show_alert=True)
            return

        data = callback.data or ""
        if data == f"{_LATEST_PREFIX}:menu":
            await callback.answer()
            await callback.message.edit_text(
                "<b>Последние подходящие вакансии</b>\n\nВыберите источник:",
                parse_mode="HTML",
                reply_markup=_latest_keyboard(source_names),
            )
            return

        parts = data.split(":")
        if len(parts) != 3 or parts[:2] != [_LATEST_PREFIX, "show"]:
            await callback.answer("Неизвестное действие.", show_alert=True)
            return
        source = source_by_token.get(parts[2])
        if source is None:
            await callback.answer("Источник больше недоступен.", show_alert=True)
            return

        vacancies = await preference_store.latest_matches(source, limit=10)
        await callback.answer()
        await callback.message.edit_text(
            format_latest_matches(source, vacancies),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="← К источникам",
                            callback_data=f"{_LATEST_PREFIX}:menu",
                        )
                    ]
                ]
            ),
            disable_web_page_preview=True,
        )

    router.message.register(start, CommandStart())
    router.message.register(status, Command("status"))
    router.message.register(show_sources, Command("sources"))
    router.message.register(show_latest, Command("latest"))
    router.callback_query.register(feedback, F.data.startswith(f"{_FEEDBACK_PREFIX}:"))
    router.callback_query.register(
        source_callback,
        F.data.startswith(f"{_SOURCE_PREFIX}:"),
    )
    router.callback_query.register(
        latest_callback,
        F.data.startswith(f"{_LATEST_PREFIX}:"),
    )

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


class TelegramNotifier:
    """Send accepted vacancies to the single configured recipient."""

    def __init__(
        self,
        bot: Bot,
        recipient_chat_id: int,
        preference_store: SourcePreferenceStore,
    ) -> None:
        self._bot = bot
        self._recipient_chat_id = recipient_chat_id
        self._preference_store = preference_store

    async def send_vacancy(self, vacancy: Vacancy, decision: Decision) -> bool:
        if not decision.accepted:
            raise ValueError("Rejected vacancies must not be sent")
        if not await self._preference_store.is_source_enabled(
            self._recipient_chat_id,
            vacancy.source,
        ):
            return False

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Открыть вакансию", url=vacancy.url)],
                [
                    InlineKeyboardButton(
                        text="⭐ Сохранить",
                        callback_data=_feedback_data(
                            "saved", vacancy.source, vacancy.external_id
                        ),
                    ),
                    InlineKeyboardButton(
                        text="👎 Не подходит",
                        callback_data=_feedback_data(
                            "rejected", vacancy.source, vacancy.external_id
                        ),
                    ),
                ],
            ]
        )
        await self._bot.send_message(
            chat_id=self._recipient_chat_id,
            text=format_vacancy(vacancy, decision),
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return True
