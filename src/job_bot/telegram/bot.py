from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from job_bot.domain import Decision, Vacancy
from job_bot.settings import Settings
from job_bot.telegram.formatting import format_vacancy


def _is_allowed(message: Message, settings: Settings) -> bool:
    return (
        settings.telegram_recipient_chat_id is not None
        and message.chat.id == settings.telegram_recipient_chat_id
    )


def create_dispatcher(settings: Settings) -> Dispatcher:
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

        if not _is_allowed(message, settings):
            await message.answer("Этот бот является приватным.")
            return

        await message.answer("Бот настроен и готов присылать подходящие вакансии.")

    async def status(message: Message) -> None:
        if not _is_allowed(message, settings):
            await message.answer("Этот бот является приватным.")
            return

        await message.answer(
            "✅ Бот работает.\n\n"
            "Фильтры: Project Manager, опыт до 3 лет, английский до B1, "
            "remote из Беларуси или hybrid в Беларуси, зарплата от $1000 "
            "либо не указана."
        )

    router.message.register(start, CommandStart())
    router.message.register(status, Command("status"))

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
                [InlineKeyboardButton(text="Открыть вакансию", url=vacancy.url)]
            ]
        )
        await self._bot.send_message(
            chat_id=self._recipient_chat_id,
            text=format_vacancy(vacancy, decision),
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
