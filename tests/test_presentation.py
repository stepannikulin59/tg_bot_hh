from __future__ import annotations

from datetime import datetime

from tg_bot_hh.presentation import build_vacancy_messages


def test_build_vacancy_messages_batches_by_ten(vacancy_factory):
    vacancies = tuple(
        vacancy_factory(
            vacancy_id=f"vac-{index}",
            name=f"Python Vacancy {index}",
            alternate_url=f"https://hh.ru/vacancy/vac-{index}",
        )
        for index in range(1, 12)
    )

    messages = build_vacancy_messages(
        vacancies,
        now=datetime(2026, 4, 12, 0, 15),
    )

    assert len(messages) == 2
    assert messages[0].startswith("Вакансии на 2026-04-12 00:15")
    assert messages[1].startswith("Вакансии на 2026-04-12 00:15")
    assert "10. Python Vacancy 10" in messages[0]
    assert "11. Python Vacancy 11" in messages[1]


def test_build_vacancy_messages_returns_empty_for_no_items():
    assert build_vacancy_messages(()) == []


def test_build_vacancy_messages_splits_long_text(vacancy_factory):
    long_title = "Python " * 300
    vacancies = (
        vacancy_factory(
            vacancy_id="vac-long",
            name=long_title,
            alternate_url="https://hh.ru/vacancy/vac-long",
        ),
    )

    messages = build_vacancy_messages(
        vacancies,
        now=datetime(2026, 4, 12, 0, 20),
        max_length=220,
    )

    assert len(messages) > 1
    assert all(
        message.startswith("Вакансии на 2026-04-12 00:20")
        for message in messages
    )
