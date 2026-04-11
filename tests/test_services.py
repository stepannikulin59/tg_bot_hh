from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tg_bot_hh.config import AppConfig
from tg_bot_hh.hh_client import HHUnavailableError
from tg_bot_hh.models import SearchPage, VacancyDetails
from tg_bot_hh.services import VacancyBotService


class InMemoryStateStore:
    def __init__(self, state):
        self.state = state

    def load(self):
        return self.state

    def save(self, state):
        self.state = state


class FakeHHClient:
    def __init__(
        self,
        pages,
        details=None,
        *,
        area_id="72",
        remote_schedule_id="remote",
        search_error=None,
    ):
        self.pages = pages
        self.details = details or {}
        self.area_id = area_id
        self.remote_schedule_id = remote_schedule_id
        self.search_error = search_error
        self.search_calls = []
        self.detail_calls = []
        self.resolve_area_calls = []
        self.resolve_remote_calls = 0

    async def resolve_area_id(self, area_name):
        self.resolve_area_calls.append(area_name)
        return self.area_id

    async def resolve_remote_schedule_id(self):
        self.resolve_remote_calls += 1
        return self.remote_schedule_id

    async def search_vacancies(self, *, page, per_page, area_id, schedule_id):
        if self.search_error is not None:
            raise self.search_error
        self.search_calls.append((area_id, schedule_id, page, per_page))
        return self.pages.get(
            (area_id, schedule_id, page),
            SearchPage(items=(), found=0, page=page, pages=0, per_page=per_page),
        )

    async def get_vacancy_details(self, vacancy_id):
        self.detail_calls.append(vacancy_id)
        details = self.details.get(vacancy_id)
        if details is not None:
            return details
        return VacancyDetails(
            vacancy_id=vacancy_id,
            description="",
            area_id=None,
            area_name=None,
            schedule_id=None,
            work_format_ids=(),
        )


def make_config() -> AppConfig:
    return AppConfig(
        telegram_bot_token="token",
        hh_user_agent="agent",
        target_area_name="Пермь",
        state_path=Path("state.json"),
        poll_interval_seconds=300,
        hh_request_limit_per_cycle=60,
    )


def make_search_page(items, page):
    return SearchPage(
        items=tuple(items),
        found=len(items),
        page=page,
        pages=1,
        per_page=100,
    )


def test_start_saves_owner_and_returns_top_ten(state_factory, vacancy_factory):
    local_items = [
        vacancy_factory(
            vacancy_id=f"vac-{index}",
            name=f"Python Vacancy {index}",
            published_at_raw=f"2026-04-11T12:{index:02d}:00+03:00",
        )
        for index in range(12)
    ]

    pages = {
        ("72", None, 0): make_search_page(local_items, page=0),
        (None, "remote", 0): make_search_page([], page=0),
    }
    service = VacancyBotService(
        config=make_config(),
        client=FakeHHClient(pages),
        state_store=InMemoryStateStore(state_factory()),
        area_id="72",
        remote_schedule_id="remote",
    )

    result = asyncio.run(service.handle_start(12345))

    assert result.accepted is True
    assert result.message is None
    assert len(result.vacancies) == 10
    assert result.vacancies[0].vacancy_id == "vac-11"
    assert result.vacancies[-1].vacancy_id == "vac-2"

    state = service.state_store.load()
    assert state.chat_id == 12345
    assert state.polling_enabled is True
    assert "vac-11" in state.seen_vacancy_ids
    assert "vac-1" not in state.seen_vacancy_ids


def test_start_from_foreign_chat_rejects_without_state_changes(state_factory):
    initial_state = state_factory(
        chat_id=12345,
        polling_enabled=True,
        seen_vacancy_ids=["vac-1"],
    )
    pages = {
        ("72", None, 0): make_search_page([], page=0),
        (None, "remote", 0): make_search_page([], page=0),
    }
    service = VacancyBotService(
        config=make_config(),
        client=FakeHHClient(pages),
        state_store=InMemoryStateStore(initial_state),
        area_id="72",
        remote_schedule_id="remote",
    )

    result = asyncio.run(service.handle_start(99999))

    assert result.accepted is False
    assert "персональный" in (result.message or "")

    state = service.state_store.load()
    assert state.chat_id == 12345
    assert state.polling_enabled is True
    assert state.seen_vacancy_ids == ("vac-1",)


def test_stop_disables_polling_without_clearing_owner(state_factory):
    initial_state = state_factory(
        chat_id=12345,
        polling_enabled=True,
        seen_vacancy_ids=["vac-1", "vac-2"],
    )
    pages = {
        ("72", None, 0): make_search_page([], page=0),
        (None, "remote", 0): make_search_page([], page=0),
    }
    service = VacancyBotService(
        config=make_config(),
        client=FakeHHClient(pages),
        state_store=InMemoryStateStore(initial_state),
        area_id="72",
        remote_schedule_id="remote",
    )

    result = asyncio.run(service.handle_stop(12345))

    assert result.accepted is True
    state = service.state_store.load()
    assert state.chat_id == 12345
    assert state.polling_enabled is False
    assert state.seen_vacancy_ids == ("vac-1", "vac-2")


def test_poll_cycle_returns_only_unseen_and_updates_floor(
    state_factory,
    vacancy_factory,
):
    old_item = vacancy_factory(
        vacancy_id="vac-old",
        name="Python old",
        published_at_raw="2026-04-11T11:00:00+03:00",
    )
    new_item = vacancy_factory(
        vacancy_id="vac-new",
        name="Python new",
        published_at_raw="2026-04-11T12:00:00+03:00",
    )
    pages = {
        ("72", None, 0): make_search_page([new_item, old_item], page=0),
        (None, "remote", 0): make_search_page([], page=0),
    }
    initial_state = state_factory(
        chat_id=12345,
        polling_enabled=True,
        seen_vacancy_ids=["vac-old"],
        pagination_floor_local=None,
        pagination_floor_remote=None,
    )
    service = VacancyBotService(
        config=make_config(),
        client=FakeHHClient(pages),
        state_store=InMemoryStateStore(initial_state),
        area_id="72",
        remote_schedule_id="remote",
    )

    unseen = asyncio.run(service.run_poll_cycle())

    assert [item.vacancy_id for item in unseen] == ["vac-new"]

    state = service.state_store.load()
    assert "vac-new" in state.seen_vacancy_ids
    assert state.pagination_floor_local == "2026-04-11T11:00:00+03:00"


def test_poll_cycle_stops_branch_when_all_items_seen(state_factory, vacancy_factory):
    page0 = [
        vacancy_factory(
            vacancy_id="seen-1",
            name="Python one",
            published_at_raw="2026-04-11T12:00:00+03:00",
        ),
        vacancy_factory(
            vacancy_id="seen-2",
            name="Python two",
            published_at_raw="2026-04-11T11:00:00+03:00",
        ),
    ]
    page1 = [
        vacancy_factory(
            vacancy_id="new-should-not-be-fetched",
            name="Python hidden",
            published_at_raw="2026-04-11T10:00:00+03:00",
        )
    ]

    pages = {
        ("72", None, 0): make_search_page(page0, page=0),
        ("72", None, 1): make_search_page(page1, page=1),
        (None, "remote", 0): make_search_page([], page=0),
    }
    client = FakeHHClient(pages)
    initial_state = state_factory(
        chat_id=12345,
        polling_enabled=True,
        seen_vacancy_ids=["seen-1", "seen-2"],
    )
    service = VacancyBotService(
        config=make_config(),
        client=client,
        state_store=InMemoryStateStore(initial_state),
        area_id="72",
        remote_schedule_id="remote",
    )

    unseen = asyncio.run(service.run_poll_cycle())

    assert unseen == ()
    local_calls = [call for call in client.search_calls if call[0] == "72"]
    assert [call[2] for call in local_calls] == [0]


def test_start_persists_owner_when_hh_temporarily_unavailable(state_factory):
    pages = {
        ("72", None, 0): make_search_page([], page=0),
        (None, "remote", 0): make_search_page([], page=0),
    }
    initial_state = state_factory()
    service = VacancyBotService(
        config=make_config(),
        client=FakeHHClient(
            pages,
            search_error=HHUnavailableError("hh is down"),
        ),
        state_store=InMemoryStateStore(initial_state),
        area_id="72",
        remote_schedule_id="remote",
    )

    with pytest.raises(HHUnavailableError):
        asyncio.run(service.handle_start(12345))

    state = service.state_store.load()
    assert state.chat_id == 12345
    assert state.polling_enabled is True


def test_start_rolls_back_state_on_non_hh_error(state_factory):
    pages = {
        ("72", None, 0): make_search_page([], page=0),
        (None, "remote", 0): make_search_page([], page=0),
    }
    initial_state = state_factory(chat_id=None, polling_enabled=False)
    service = VacancyBotService(
        config=make_config(),
        client=FakeHHClient(
            pages,
            search_error=RuntimeError("broken parser"),
        ),
        state_store=InMemoryStateStore(initial_state),
        area_id="72",
        remote_schedule_id="remote",
    )

    with pytest.raises(RuntimeError):
        asyncio.run(service.handle_start(12345))

    state = service.state_store.load()
    assert state.chat_id is None
    assert state.polling_enabled is False


def test_service_resolves_branch_filters_lazily_once(state_factory):
    pages = {
        ("72", None, 0): make_search_page([], page=0),
        (None, "remote", 0): make_search_page([], page=0),
    }
    client = FakeHHClient(pages)
    service = VacancyBotService(
        config=make_config(),
        client=client,
        state_store=InMemoryStateStore(state_factory()),
    )

    async def run_scenario():
        await service.handle_start(12345)
        await service.handle_start(12345)

    asyncio.run(run_scenario())

    assert client.resolve_area_calls == ["Пермь"]
    assert client.resolve_remote_calls == 1
