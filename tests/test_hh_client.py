from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from tg_bot_hh.hh_client import AreaResolutionError, HHClient, HHUnavailableError


def build_client(handler):
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(
        base_url="https://api.hh.ru",
        transport=transport,
        headers={
            "HH-User-Agent": "tg-bot-hh/1.0 (test@example.com)",
            "User-Agent": "tg-bot-hh/1.0 (test@example.com)",
            "Accept": "application/json",
        },
    )
    return HHClient(
        base_url="https://api.hh.ru",
        user_agent="tg-bot-hh/1.0 (test@example.com)",
        timeout_seconds=5,
        client=async_client,
    )


def test_search_vacancies_sends_required_headers_and_multi_experience():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["query"] = parse_qs(request.url.query.decode())
        payload = {
            "found": 1,
            "page": 0,
            "pages": 1,
            "per_page": 100,
            "items": [
                {
                    "id": "1",
                    "name": "Python Developer",
                    "employer": {"name": "Acme"},
                    "area": {"id": "72", "name": "Пермь"},
                    "alternate_url": "https://hh.ru/vacancy/1",
                    "published_at": "2026-04-11T12:00:00+0300",
                    "salary": None,
                    "schedule": {"id": "remote"},
                    "work_format": [{"id": "REMOTE"}],
                    "snippet": {
                        "requirement": "Python",
                        "responsibility": "API",
                    },
                }
            ],
        }
        return httpx.Response(200, json=payload)

    client = build_client(handler)
    page = asyncio.run(
        client.search_vacancies(
            page=0,
            per_page=100,
            area_id="72",
            schedule_id="remote",
        )
    )

    assert page.items[0].vacancy_id == "1"
    assert captured["headers"]["hh-user-agent"] == "tg-bot-hh/1.0 (test@example.com)"
    assert captured["headers"]["user-agent"] == "tg-bot-hh/1.0 (test@example.com)"
    assert captured["query"]["professional_role"] == ["96"]
    assert captured["query"]["order_by"] == ["publication_time"]
    assert captured["query"]["experience"] == ["noExperience", "between1And3"]
    assert captured["query"]["area"] == ["72"]
    assert captured["query"]["schedule"] == ["remote"]


def test_client_retries_429_with_backoff(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(
                429,
                json={"errors": [{"type": "too_many_requests"}]},
            )
        return httpx.Response(
            200,
            json={
                "found": 0,
                "page": 0,
                "pages": 0,
                "per_page": 100,
                "items": [],
            },
        )

    monkeypatch.setattr("tg_bot_hh.hh_client.asyncio.sleep", fake_sleep)
    client = build_client(handler)
    page = asyncio.run(
        client.search_vacancies(page=0, per_page=100, area_id="72", schedule_id=None)
    )

    assert page.items == ()
    assert calls["count"] == 2
    assert sleeps == [1]


def test_resolve_area_id_requires_single_leaf_match():
    areas = [
        {
            "id": "113",
            "name": "Россия",
            "areas": [
                {"id": "72", "name": "Пермь", "areas": []},
                {"id": "999", "name": "Пермь", "areas": []},
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(areas).encode("utf-8"))

    client = build_client(handler)

    try:
        asyncio.run(client.resolve_area_id("Пермь"))
    except AreaResolutionError as exc:
        assert "matched multiple leaf ids" in str(exc)
    else:
        raise AssertionError("Expected AreaResolutionError for duplicate city names")


def test_client_wraps_transport_errors_as_hh_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("network timeout")

    client = build_client(handler)

    with pytest.raises(HHUnavailableError):
        asyncio.run(
            client.search_vacancies(
                page=0,
                per_page=100,
                area_id="72",
                schedule_id=None,
            )
        )


def test_client_treats_503_as_hh_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"errors": [{"type": "service_unavailable"}]})

    client = build_client(handler)

    with pytest.raises(HHUnavailableError):
        asyncio.run(
            client.search_vacancies(
                page=0,
                per_page=100,
                area_id="72",
                schedule_id=None,
            )
        )
