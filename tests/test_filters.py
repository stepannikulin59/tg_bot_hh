from __future__ import annotations

from tg_bot_hh.filters import (
    merge_and_sort_vacancies,
    page_stop_decision,
    text_has_keyword,
    title_has_keyword,
)


def test_keyword_boundaries(vacancy_factory):
    assert title_has_keyword("Senior Java developer", ["java"]) is True
    assert title_has_keyword("Senior JavaScript developer", ["java"]) is False
    assert title_has_keyword("Golang backend engineer", ["go"]) is False
    assert title_has_keyword("Golang backend engineer", ["golang"]) is True
    assert title_has_keyword("C# backend engineer", ["c#"]) is True
    assert title_has_keyword("C++ systems engineer", ["c++"]) is True
    assert title_has_keyword(".NET platform engineer", [".net"]) is True

    vacancy = vacancy_factory(
        name="Backend engineer",
        snippet_text="Experience with Python and Django",
    )
    assert text_has_keyword(vacancy.name, vacancy.snippet_text, ["python"]) is True


def test_merge_deduplicates_and_sorts_by_published_at(vacancy_factory):
    local_branch = [
        vacancy_factory(
            vacancy_id="local-1",
            name="Local old",
            published_at_raw="2026-04-11T10:00:00+03:00",
        ),
        vacancy_factory(
            vacancy_id="shared",
            name="Shared old",
            published_at_raw="2026-04-11T11:00:00+03:00",
        ),
    ]
    remote_branch = [
        vacancy_factory(
            vacancy_id="remote-1",
            name="Remote newest",
            published_at_raw="2026-04-11T12:00:00+03:00",
        ),
        vacancy_factory(
            vacancy_id="shared",
            name="Shared newer",
            published_at_raw="2026-04-11T11:30:00+03:00",
        ),
    ]

    merged = merge_and_sort_vacancies(local_branch, remote_branch)

    assert [vacancy.vacancy_id for vacancy in merged] == [
        "remote-1",
        "shared",
        "local-1",
    ]


def test_page_stop_decision_uses_floor_only_without_unseen(vacancy_factory):
    items = (
        vacancy_factory(
            vacancy_id="seen-1",
            published_at_raw="2026-04-11T11:00:00+03:00",
        ),
        vacancy_factory(
            vacancy_id="seen-2",
            published_at_raw="2026-04-11T10:00:00+03:00",
        ),
    )

    all_seen, floor_reached_without_new, min_published_at_raw = page_stop_decision(
        items=items,
        seen_ids={"seen-1", "seen-2"},
        pagination_floor="2026-04-11T10:30:00+03:00",
    )

    assert all_seen is True
    assert floor_reached_without_new is True
    assert min_published_at_raw == "2026-04-11T10:00:00+03:00"


def test_page_stop_decision_does_not_stop_when_unseen_exists(vacancy_factory):
    items = (
        vacancy_factory(
            vacancy_id="seen-1",
            published_at_raw="2026-04-11T11:00:00+03:00",
        ),
        vacancy_factory(
            vacancy_id="new-1",
            published_at_raw="2026-04-11T10:00:00+03:00",
        ),
    )

    all_seen, floor_reached_without_new, _ = page_stop_decision(
        items=items,
        seen_ids={"seen-1"},
        pagination_floor="2026-04-11T11:30:00+03:00",
    )

    assert all_seen is False
    assert floor_reached_without_new is False
