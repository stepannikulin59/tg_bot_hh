from __future__ import annotations

import asyncio
import logging
from typing import cast

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from .config import AppConfig
from .hh_client import HHClientError, HHForbiddenError, HHUnavailableError
from .presentation import build_vacancy_messages
from .services import VacancyBotService

LOGGER = logging.getLogger(__name__)
SERVICE_BOT_DATA_KEY = "vacancy_service"
ERROR_ALERT_ACTIVE_BOT_DATA_KEY = "error_alert_active"
ERROR_ALERT_KIND_BOT_DATA_KEY = "error_alert_kind"


def _classify_runtime_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, HHForbiddenError):
        return (
            "hh_forbidden",
            "hh.ru отклонил доступ (403). Проверьте HH_USER_AGENT и лимиты запросов.",
        )
    if isinstance(exc, HHUnavailableError):
        return (
            "hh_unavailable",
            "hh.ru временно недоступен. Продолжаю попытки автоопроса.",
        )
    return ("unknown", "Произошла ошибка автоопроса. Продолжаю попытки.")


async def _send_message_with_retry(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    attempts: int = 3,
    delay_seconds: float = 1.0,
) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            return True
        except (TimedOut, NetworkError):
            LOGGER.warning(
                "Failed to send Telegram message to chat_id=%s (attempt %s/%s)",
                chat_id,
                attempt,
                attempts,
                exc_info=True,
            )
            if attempt >= attempts:
                return False
            await asyncio.sleep(delay_seconds)
    return False


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
            await _send_message_with_retry(
                context=context,
                chat_id=chat_id,
                text="Подходящих вакансий сейчас нет.",
            )
        return
    for text in messages:
        sent = await _send_message_with_retry(
            context=context,
            chat_id=chat_id,
            text=text,
        )
        if not sent:
            break


def _get_service(application: Application) -> VacancyBotService:
    service = application.bot_data.get(SERVICE_BOT_DATA_KEY)
    if service is None:
        raise RuntimeError("Vacancy service is not initialized")
    return cast(VacancyBotService, service)


async def _notify_outage_once(
    application: Application,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    kind: str,
    text: str,
) -> None:
    active = bool(application.bot_data.get(ERROR_ALERT_ACTIVE_BOT_DATA_KEY))
    current_kind = application.bot_data.get(ERROR_ALERT_KIND_BOT_DATA_KEY)
    if active and current_kind == kind:
        return
    application.bot_data[ERROR_ALERT_ACTIVE_BOT_DATA_KEY] = True
    application.bot_data[ERROR_ALERT_KIND_BOT_DATA_KEY] = kind
    await _send_message_with_retry(context=context, chat_id=chat_id, text=text)


async def _notify_recovery_if_needed(
    application: Application,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
) -> None:
    if not application.bot_data.get(ERROR_ALERT_ACTIVE_BOT_DATA_KEY):
        return
    application.bot_data[ERROR_ALERT_ACTIVE_BOT_DATA_KEY] = False
    application.bot_data[ERROR_ALERT_KIND_BOT_DATA_KEY] = None
    await _send_message_with_retry(
        context=context,
        chat_id=chat_id,
        text="Работа автоопроса восстановлена.",
    )


def build_application(config: AppConfig) -> Application:
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        LOGGER.exception("Unhandled Telegram update error", exc_info=context.error)

    async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if chat is None:
            return

        service = _get_service(context.application)
        try:
            result = await service.handle_start(chat.id)
        except HHForbiddenError:
            await _send_message_with_retry(
                context=context,
                chat_id=chat.id,
                text="hh.ru отклонил доступ (403). Проверьте HH_USER_AGENT и попробуйте позже.",
            )
            return
        except HHUnavailableError:
            LOGGER.warning("hh.ru is unavailable while processing /start", exc_info=True)
            await _send_message_with_retry(
                context=context,
                chat_id=chat.id,
                text="hh.ru временно недоступен. Автоопрос включен и продолжит попытки.",
            )
            return
        except HHClientError:
            LOGGER.warning("hh.ru client error while processing /start", exc_info=True)
            await _send_message_with_retry(
                context=context,
                chat_id=chat.id,
                text="Ошибка при запросе к hh.ru. Попробуйте позже.",
            )
            return
        except Exception:
            LOGGER.exception("Failed to process /start")
            await _send_message_with_retry(
                context=context,
                chat_id=chat.id,
                text="Не удалось обработать /start.",
            )
            return

        if result.message:
            await _send_message_with_retry(
                context=context,
                chat_id=chat.id,
                text=result.message,
            )
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

        service = _get_service(context.application)
        try:
            result = await service.handle_stop(chat.id)
        except Exception:
            LOGGER.exception("Failed to process /stop")
            await _send_message_with_retry(
                context=context,
                chat_id=chat.id,
                text="Не удалось обработать /stop.",
            )
            return

        await _send_message_with_retry(
            context=context,
            chat_id=chat.id,
            text=result.message,
        )

    async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        application = context.application
        service = _get_service(application)
        state = service.state_store.load()
        if state.chat_id is None or not state.polling_enabled:
            return

        try:
            vacancies = await service.run_poll_cycle()
        except Exception as exc:
            kind, text = _classify_runtime_error(exc)
            if kind == "unknown":
                LOGGER.exception("Polling cycle failed")
            else:
                LOGGER.warning("Polling cycle failed with kind=%s", kind, exc_info=True)
            await _notify_outage_once(
                application,
                context,
                chat_id=state.chat_id,
                kind=kind,
                text=text,
            )
            return

        await _notify_recovery_if_needed(application, context, chat_id=state.chat_id)
        if not vacancies:
            return
        await _send_vacancy_batches(
            chat_id=state.chat_id,
            context=context,
            vacancies=vacancies,
            send_empty_message=False,
        )

    async def post_init(application: Application) -> None:
        if application.job_queue is None:
            raise RuntimeError("python-telegram-bot must be installed with job-queue support")

        application.bot_data[SERVICE_BOT_DATA_KEY] = await VacancyBotService.build(config=config)
        application.bot_data[ERROR_ALERT_ACTIVE_BOT_DATA_KEY] = False
        application.bot_data[ERROR_ALERT_KIND_BOT_DATA_KEY] = None
        application.job_queue.run_repeating(
            poll_job,
            interval=config.poll_interval_seconds,
            first=config.poll_interval_seconds,
            name="tg_bot_hh_poll",
        )

    async def post_shutdown(application: Application) -> None:
        service = application.bot_data.get(SERVICE_BOT_DATA_KEY)
        if service is None:
            return
        try:
            await cast(VacancyBotService, service).client.aclose()
        except Exception:
            LOGGER.exception("Failed to close hh client")

    application = (
        ApplicationBuilder()
        .token(config.telegram_bot_token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("stop", stop_handler))
    application.add_error_handler(error_handler)
    return application
