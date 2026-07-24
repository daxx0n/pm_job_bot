from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from job_bot.domain import Decision, Vacancy
from job_bot.settings import Settings
from job_bot.storage import (
    VacancyFeedbackStore,
    feedback_external_id_token,
    feedback_source_token,
)
from job_bot.telegram.formatting import format_vacancy

_FEEDBACK_PREFIX = "fb"
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


def create_dispatcher(
    settings: Settings,
    feedback_store: VacancyFeedbackStore | None = None,
) -> Dispatcher:
    router = Router(name="commands")

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

        await message.answer("Бот настроен и готов присылать подходящие вакансии.")

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

    router.message.register(start, CommandStart())
    router.message.register(status, Command("status"))
    router.callback_query.register(feedback)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


class TelegramNotifier:
    """Send accepted vacancies to the single configured recipient."""

    def __init__(self, bot: Bot, recipient_chat_id: int) -> None:
        self._bot = bot
        self._recipient_chat_id = recipient_chat_id

    async def send_vacancy(self, vacancy: Vacancy, decision: Decision) -> None:
        if not decision.accepted:
            raise ValueError("Rejected vacancies must not be sent")

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
