from __future__ import annotations

import asyncio

from tg_bot_hh.telegram_app import _send_vacancy_batches


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, *, chat_id, text):
        self.messages.append((chat_id, text))


class FakeContext:
    def __init__(self, bot):
        self.bot = bot


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
