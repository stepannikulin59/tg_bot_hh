from __future__ import annotations

import asyncio
from pathlib import Path

from telegram.error import TimedOut

from tg_bot_hh.config import AppConfig
from tg_bot_hh.hh_client import HHForbiddenError, HHUnavailableError
from tg_bot_hh.models import StartCommandResult, StopCommandResult
from tg_bot_hh.telegram_app import (
    _send_vacancy_batches,
    _send_message_with_retry,
    build_application,
)


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))


class FakeContext:
    def __init__(self, bot, application=None):
        self.bot = bot
        self.application = application


class FakeJobQueue:
    def __init__(self):
        self.calls = []

    def run_repeating(self, callback, interval, first, name):
        self.calls.append(
            {
                "callback": callback,
                "interval": interval,
                "first": first,
                "name": name,
            }
        )


class FakeApplication:
    def __init__(self):
        self.bot_data = {}
        self.job_queue = FakeJobQueue()
        self.handlers = []
        self.error_handlers = []
        self.post_init_callback = None
        self.post_shutdown_callback = None

    def add_handler(self, handler):
        self.handlers.append(handler)

    def add_error_handler(self, handler):
        self.error_handlers.append(handler)


class FakeApplicationBuilder:
    def __init__(self):
        self._token = None
        self._connect_timeout = None
        self._read_timeout = None
        self._write_timeout = None
        self._post_init = None
        self._post_shutdown = None
        self.application = FakeApplication()

    def token(self, token):
        self._token = token
        return self

    def connect_timeout(self, timeout):
        self._connect_timeout = timeout
        return self

    def read_timeout(self, timeout):
        self._read_timeout = timeout
        return self

    def write_timeout(self, timeout):
        self._write_timeout = timeout
        return self

    def post_init(self, callback):
        self._post_init = callback
        return self

    def post_shutdown(self, callback):
        self._post_shutdown = callback
        return self

    def build(self):
        self.application.post_init_callback = self._post_init
        self.application.post_shutdown_callback = self._post_shutdown
        return self.application


class StaticStateStore:
    def __init__(self, state):
        self._state = state

    def load(self):
        return self._state


class RuntimeServiceStub:
    def __init__(
        self,
        *,
        config,
        state_store,
        poll_results,
        start_result=None,
        start_error=None,
        stop_result=None,
    ):
        self.config = config
        self.state_store = state_store
        self._poll_results = list(poll_results)
        self._poll_index = 0
        self._start_result = start_result or StartCommandResult(
            accepted=True,
            message=None,
            vacancies=(),
        )
        self._start_error = start_error
        self._stop_result = stop_result or StopCommandResult(
            accepted=True,
            message="stopped",
        )
        self.start_calls = []
        self.client = self._ClientStub()

    class _ClientStub:
        async def aclose(self):
            return None

    async def run_poll_cycle(self):
        result = self._poll_results[self._poll_index]
        self._poll_index += 1
        if isinstance(result, Exception):
            raise result
        return result

    async def handle_start(self, chat_id):
        self.start_calls.append(chat_id)
        if self._start_error is not None:
            raise self._start_error
        return self._start_result

    async def handle_stop(self, chat_id):
        return self._stop_result


def test_send_vacancy_batches_does_not_send_empty_when_disabled():
    bot = FakeBot()
    context = FakeContext(bot)

    asyncio.run(
        _send_vacancy_batches(
            chat_id=123,
            context=context,
            vacancies=(),
            send_empty_message=False,
        )
    )

    assert bot.messages == []


def test_send_vacancy_batches_sends_empty_message_when_enabled():
    bot = FakeBot()
    context = FakeContext(bot)

    asyncio.run(
        _send_vacancy_batches(
            chat_id=123,
            context=context,
            vacancies=(),
            send_empty_message=True,
        )
    )

    assert bot.messages == [
        (123, "Подходящих вакансий сейчас нет."),
    ]


def test_send_vacancy_batches_sends_multiple_messages_by_ten(vacancy_factory):
    bot = FakeBot()
    context = FakeContext(bot)
    vacancies = tuple(
        vacancy_factory(
            vacancy_id=f"vac-{index}",
            name=f"Python Vacancy {index}",
            alternate_url=f"https://hh.ru/vacancy/{index}",
        )
        for index in range(1, 12)
    )

    asyncio.run(
        _send_vacancy_batches(
            chat_id=123,
            context=context,
            vacancies=vacancies,
            send_empty_message=False,
        )
    )

    assert len(bot.messages) == 2
    assert all("Вакансии на" in text for _, text in bot.messages)


def test_send_message_with_retry_succeeds_after_timeout(monkeypatch):
    class FlakyBot:
        def __init__(self):
            self.calls = 0
            self.messages = []

        async def send_message(self, *, chat_id, text):
            self.calls += 1
            if self.calls == 1:
                raise TimedOut("temporary timeout")
            self.messages.append((chat_id, text))

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("tg_bot_hh.telegram_app.asyncio.sleep", no_sleep)

    bot = FlakyBot()
    context = FakeContext(bot=bot)
    sent = asyncio.run(
        _send_message_with_retry(
            context=context,
            chat_id=123,
            text="hello",
        )
    )

    assert sent is True
    assert bot.calls == 2
    assert bot.messages == [(123, "hello")]


def make_config() -> AppConfig:
    return AppConfig(
        telegram_bot_token="token",
        hh_user_agent="agent",
        target_area_name="Пермь",
        state_path=Path("state.db"),
        poll_interval_seconds=300,
        hh_request_limit_per_cycle=60,
    )


def test_build_application_creates_service_in_post_init(monkeypatch, state_factory):
    config = make_config()
    fake_builder = FakeApplicationBuilder()
    built_service = RuntimeServiceStub(
        config=config,
        state_store=StaticStateStore(state_factory()),
        poll_results=[()],
    )
    build_calls = []

    class FakeVacancyBotService:
        @classmethod
        async def build(cls, *, config, client=None, state_store=None):
            build_calls.append(config)
            return built_service

    monkeypatch.setattr("tg_bot_hh.telegram_app.ApplicationBuilder", lambda: fake_builder)
    monkeypatch.setattr("tg_bot_hh.telegram_app.VacancyBotService", FakeVacancyBotService)

    app = build_application(config)

    assert app is fake_builder.application
    assert build_calls == []

    asyncio.run(app.post_init_callback(app))

    assert build_calls == [config]
    assert app.job_queue.calls[0]["interval"] == config.poll_interval_seconds


def test_poll_job_notifies_hh_outage_once_and_reports_recovery(
    monkeypatch,
    state_factory,
    vacancy_factory,
):
    config = make_config()
    state = state_factory(chat_id=12345, polling_enabled=True)
    vacancy = vacancy_factory(vacancy_id="vac-1", name="Python Vacancy")
    fake_service = RuntimeServiceStub(
        config=config,
        state_store=StaticStateStore(state),
        poll_results=[
            HHUnavailableError("temporary outage"),
            HHUnavailableError("temporary outage"),
            (vacancy,),
        ],
    )
    fake_builder = FakeApplicationBuilder()

    class FakeVacancyBotService:
        @classmethod
        async def build(cls, *, config, client=None, state_store=None):
            return fake_service

    monkeypatch.setattr("tg_bot_hh.telegram_app.ApplicationBuilder", lambda: fake_builder)
    monkeypatch.setattr("tg_bot_hh.telegram_app.VacancyBotService", FakeVacancyBotService)

    app = build_application(config)
    asyncio.run(app.post_init_callback(app))

    poll_job = app.job_queue.calls[0]["callback"]
    bot = FakeBot()
    context = FakeContext(bot=bot, application=app)

    async def run_poll_cycles():
        await poll_job(context)
        await poll_job(context)
        await poll_job(context)

    asyncio.run(run_poll_cycles())

    texts = [text for _, text in bot.messages]
    assert sum("временно недоступен" in text for text in texts) == 1
    assert sum("восстановлена" in text for text in texts) == 1
    assert any("Вакансии на" in text for text in texts)


def test_start_handler_handles_hh_forbidden(
    monkeypatch,
    state_factory,
):
    config = make_config()
    state = state_factory(chat_id=12345, polling_enabled=True)
    fake_service = RuntimeServiceStub(
        config=config,
        state_store=StaticStateStore(state),
        poll_results=[()],
        start_error=HHForbiddenError("forbidden"),
    )
    fake_builder = FakeApplicationBuilder()

    class FakeVacancyBotService:
        @classmethod
        async def build(cls, *, config, client=None, state_store=None):
            return fake_service

    monkeypatch.setattr("tg_bot_hh.telegram_app.ApplicationBuilder", lambda: fake_builder)
    monkeypatch.setattr("tg_bot_hh.telegram_app.VacancyBotService", FakeVacancyBotService)

    app = build_application(config)
    asyncio.run(app.post_init_callback(app))

    start_handler = next(
        handler.callback for handler in app.handlers if "start" in handler.commands
    )

    class FakeChat:
        def __init__(self, chat_id):
            self.id = chat_id

    class FakeUpdate:
        def __init__(self, chat_id):
            self.effective_chat = FakeChat(chat_id)

    context = FakeContext(bot=FakeBot(), application=app)
    asyncio.run(start_handler(FakeUpdate(12345), context))

    assert any("403" in text for _, text in context.bot.messages)


def test_poll_job_notifies_hh_forbidden_once_and_recovery(
    monkeypatch,
    state_factory,
    vacancy_factory,
):
    config = make_config()
    state = state_factory(chat_id=12345, polling_enabled=True)
    vacancy = vacancy_factory(vacancy_id="vac-1", name="Python Vacancy")
    fake_service = RuntimeServiceStub(
        config=config,
        state_store=StaticStateStore(state),
        poll_results=[
            HHForbiddenError("forbidden"),
            HHForbiddenError("forbidden"),
            (vacancy,),
        ],
    )
    fake_builder = FakeApplicationBuilder()

    class FakeVacancyBotService:
        @classmethod
        async def build(cls, *, config, client=None, state_store=None):
            return fake_service

    monkeypatch.setattr("tg_bot_hh.telegram_app.ApplicationBuilder", lambda: fake_builder)
    monkeypatch.setattr("tg_bot_hh.telegram_app.VacancyBotService", FakeVacancyBotService)

    app = build_application(config)
    asyncio.run(app.post_init_callback(app))

    poll_job = app.job_queue.calls[0]["callback"]
    bot = FakeBot()
    context = FakeContext(bot=bot, application=app)

    async def run_poll_cycles():
        await poll_job(context)
        await poll_job(context)
        await poll_job(context)

    asyncio.run(run_poll_cycles())

    texts = [text for _, text in bot.messages]
    assert sum("403" in text for text in texts) == 1
    assert sum("восстановлена" in text for text in texts) == 1
