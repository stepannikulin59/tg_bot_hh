from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from .presentation import build_vacancy_messages
from .services import VacancyBotService

LOGGER = logging.getLogger(__name__)


async def _send_vacancy_batches(
    *,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    vacancies: tuple,
    send_empty_message: bool,
) -> None:
    messages = build_vacancy_messages(vacancies)
    if not messages:
        if send_empty_message:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Подходящих вакансий сейчас нет.",
            )
        return

    for text in messages:
        await context.bot.send_message(chat_id=chat_id, text=text)


def build_application(bot_token: str, service: VacancyBotService) -> Application:
    async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if chat is None:
            return

        try:
            result = await service.handle_start(chat.id)
        except Exception:
            LOGGER.exception("Failed to process /start")
            await context.bot.send_message(
                chat_id=chat.id,
                text="Не удалось обработать /start.",
            )
            return

        if result.message:
            await context.bot.send_message(chat_id=chat.id, text=result.message)

        if result.accepted:
            await _send_vacancy_batches(
                chat_id=chat.id,
                context=context,
                vacancies=result.vacancies,
                send_empty_message=True,
            )

    async def stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if chat is None:
            return

        try:
            result = await service.handle_stop(chat.id)
        except Exception:
            LOGGER.exception("Failed to process /stop")
            await context.bot.send_message(
                chat_id=chat.id,
                text="Не удалось обработать /stop.",
            )
            return

        await context.bot.send_message(chat_id=chat.id, text=result.message)

    async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            vacancies = await service.run_poll_cycle()
            state = service.state_store.load()
        except Exception:
            LOGGER.exception("Polling cycle failed")
            return

        if state.chat_id is None or not vacancies:
            return

        await _send_vacancy_batches(
            chat_id=state.chat_id,
            context=context,
            vacancies=vacancies,
            send_empty_message=False,
        )

    async def post_init(application: Application) -> None:
        if application.job_queue is None:
            raise RuntimeError(
                "python-telegram-bot must be installed with job-queue support"
            )

        application.job_queue.run_repeating(
            poll_job,
            interval=service.config.poll_interval_seconds,
            first=service.config.poll_interval_seconds,
            name="tg_bot_hh_poll",
        )

    application = ApplicationBuilder().token(bot_token).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("stop", stop_handler))
    return application
