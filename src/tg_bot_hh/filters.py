from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .models import DEFAULT_KEYWORDS, VacancySummary, parse_hh_datetime

KEYWORD_PATTERNS = {
    "c#": re.compile(r"(?<![\w.+#])c#(?![\w+#])", re.IGNORECASE),
    "c++": re.compile(r"(?<![\w.+#])c\+\+(?![\w+#])", re.IGNORECASE),
    "go": re.compile(r"(?<![\w.+#])go(?![\w+#])", re.IGNORECASE),
    "golang": re.compile(r"(?<![\w.+#])golang(?![\w+#])", re.IGNORECASE),
    "java": re.compile(r"(?<![\w.+#])java(?![\w+#])", re.IGNORECASE),
    "python": re.compile(r"(?<![\w.+#])python(?![\w+#])", re.IGNORECASE),
    ".net": re.compile(r"(?<![\w.+#])\.net(?![\w+#])", re.IGNORECASE),
}


@dataclass(frozen=True, slots=True)
class PageStopDecision:
    all_seen: bool
    floor_reached_without_new: bool
    min_published_at_raw: str | None


def normalize_text(*parts: str | None) -> str:
    return re.sub(r"\s+", " ", " ".join(part or "" for part in parts)).strip()


def title_has_keyword(
    title: str,
    keywords: Sequence[str] = DEFAULT_KEYWORDS,
) -> bool:
    normalized = normalize_text(title)
    return any(
        KEYWORD_PATTERNS[keyword.lower()].search(normalized)
        for keyword in keywords
    )


def text_has_keyword(
    title: str,
    description: str,
    keywords: Sequence[str] = DEFAULT_KEYWORDS,
) -> bool:
    normalized = normalize_text(title, description)
    return any(
        KEYWORD_PATTERNS[keyword.lower()].search(normalized)
        for keyword in keywords
    )


def sort_vacancies(
    vacancies: Iterable[VacancySummary],
) -> tuple[VacancySummary, ...]:
    return tuple(
        sorted(
            vacancies,
            key=lambda item: parse_hh_datetime(item.published_at_raw),
            reverse=True,
        )
    )


def merge_and_sort_vacancies(
    local_vacancies: Iterable[VacancySummary],
    remote_vacancies: Iterable[VacancySummary],
) -> tuple[VacancySummary, ...]:
    by_id: dict[str, VacancySummary] = {}

    for vacancy in [*local_vacancies, *remote_vacancies]:
        current = by_id.get(vacancy.vacancy_id)
        if current is None:
            by_id[vacancy.vacancy_id] = vacancy
            continue

        current_date = parse_hh_datetime(current.published_at_raw)
        next_date = parse_hh_datetime(vacancy.published_at_raw)
        if next_date > current_date:
            by_id[vacancy.vacancy_id] = vacancy

    return sort_vacancies(by_id.values())


def page_stop_decision(
    items: tuple[VacancySummary, ...],
    seen_ids: set[str],
    pagination_floor: str | None,
) -> PageStopDecision:
    if not items:
        return PageStopDecision(
            all_seen=False,
            floor_reached_without_new=False,
            min_published_at_raw=None,
        )

    all_seen = all(item.vacancy_id in seen_ids for item in items)
    min_item = min(items, key=lambda item: item.published_at)

    floor_reached_without_new = False
    has_unseen = any(item.vacancy_id not in seen_ids for item in items)
    if pagination_floor is not None and not has_unseen:
        floor_reached_without_new = (
            min_item.published_at <= parse_hh_datetime(pagination_floor)
        )

    return PageStopDecision(
        all_seen=all_seen,
        floor_reached_without_new=floor_reached_without_new,
        min_published_at_raw=min_item.published_at_raw,
    )
