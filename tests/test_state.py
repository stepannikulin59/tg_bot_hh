from __future__ import annotations

def test_seen_ids_are_fifo_capped_at_1000(state_factory):
    state = state_factory(
        seen_vacancy_ids=[f"vac-{index:04d}" for index in range(1000)],
        pagination_floor_local="2026-04-11T10:00:00+03:00",
        pagination_floor_remote="2026-04-11T10:00:00+03:00",
    )

    updated = state.with_seen_vacancies(["vac-1000"])

    seen_ids = list(updated.seen_vacancy_ids)
    assert len(seen_ids) == 1000
    assert seen_ids[0] == "vac-0001"
    assert seen_ids[-1] == "vac-1000"
    assert "vac-0000" not in seen_ids


def test_eviction_resets_pagination_floors(state_factory):
    state = state_factory(
        seen_vacancy_ids=[f"vac-{index:04d}" for index in range(1000)],
        pagination_floor_local="2026-04-11T10:00:00+03:00",
        pagination_floor_remote="2026-04-11T10:00:00+03:00",
    )

    updated = state.with_seen_vacancies(["vac-1000"])

    assert updated.pagination_floor_local is None
    assert updated.pagination_floor_remote is None


def test_has_seen_checks_membership_without_side_effects(state_factory):
    state = state_factory(seen_vacancy_ids=["vac-1", "vac-2"])

    assert state.has_seen("vac-1") is True
    assert state.has_seen("vac-3") is False
