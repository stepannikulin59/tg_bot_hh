from __future__ import annotations

from datetime import datetime

import pytest

from tg_bot_hh.models import BotState, Salary, VacancySummary, parse_hh_datetime


@pytest.fixture
def vacancy_factory():
    def factory(**overrides):
        raw_dt = overrides.pop("published_at_raw", "2026-04-11T12:00:00+03:00")

        payload = {
            "vacancy_id": "vac-1",
            "name": "Senior Python Developer",
            "employer_name": "Acme",
            "area_id": "72",
            "area_name": "Пермь",
            "alternate_url": "https://hh.ru/vacancy/vac-1",
            "published_at_raw": raw_dt,
            "published_at": parse_hh_datetime(raw_dt),
            "salary": Salary(from_amount=None, to_amount=None, currency=None),
            "schedule_id": "remote",
            "work_format_ids": ("REMOTE",),
            "snippet_text": "Python backend",
        }
        payload.update(overrides)

        published_at = payload.get("published_at")
        if isinstance(published_at, str):
            payload["published_at"] = parse_hh_datetime(published_at)
        elif isinstance(published_at, datetime):
            payload["published_at"] = published_at

        return VacancySummary(**payload)

    return factory


@pytest.fixture
def state_factory():
    def factory(**overrides):
        payload = {
            "schema_version": 1,
            "chat_id": None,
            "polling_enabled": False,
            "seen_vacancy_ids": (),
            "pagination_floor_local": None,
            "pagination_floor_remote": None,
        }
        payload.update(overrides)

        payload["seen_vacancy_ids"] = tuple(payload["seen_vacancy_ids"])
        return BotState(**payload)

    return factory
