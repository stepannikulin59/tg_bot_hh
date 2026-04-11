from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

MAX_SEEN_VACANCIES = 1000
MAX_VACANCY_SEARCH_DEPTH = 2000
DEFAULT_KEYWORDS = ("c#", "c++", "go", "golang", "java", "python", ".net")
TARGET_PROFESSIONAL_ROLE = "96"
TARGET_EXPERIENCE = ("noExperience", "between1And3")

BranchName = Literal["local", "remote"]


def parse_hh_datetime(value: str) -> datetime:
    normalized = value.strip()
    if len(normalized) >= 5 and normalized[-5] in {"+", "-"} and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    return datetime.fromisoformat(normalized)


@dataclass(frozen=True, slots=True)
class Salary:
    from_amount: int | None
    to_amount: int | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class VacancySummary:
    vacancy_id: str
    name: str
    employer_name: str
    area_id: str | None
    area_name: str | None
    alternate_url: str
    published_at_raw: str
    published_at: datetime
    salary: Salary | None
    schedule_id: str | None
    work_format_ids: tuple[str, ...]
    snippet_text: str


@dataclass(frozen=True, slots=True)
class VacancyDetails:
    vacancy_id: str
    description: str
    area_id: str | None
    area_name: str | None
    schedule_id: str | None
    work_format_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[VacancySummary, ...]
    found: int
    page: int
    pages: int
    per_page: int


@dataclass(frozen=True, slots=True)
class BotState:
    chat_id: int | None = None
    polling_enabled: bool = False
    seen_vacancy_ids: tuple[str, ...] = ()
    pagination_floor_local: str | None = None
    pagination_floor_remote: str | None = None
    schema_version: int = 1

    def has_seen(self, vacancy_id: str) -> bool:
        return vacancy_id in self.seen_vacancy_ids

    def with_seen_vacancies(self, vacancy_ids: list[str]) -> "BotState":
        seen = list(self.seen_vacancy_ids)
        seen_set = set(seen)
        added = False

        for vacancy_id in vacancy_ids:
            if vacancy_id in seen_set:
                continue
            seen.append(vacancy_id)
            seen_set.add(vacancy_id)
            added = True

        evicted = False
        while len(seen) > MAX_SEEN_VACANCIES:
            evicted = True
            removed = seen.pop(0)
            seen_set.discard(removed)

        local_floor = self.pagination_floor_local
        remote_floor = self.pagination_floor_remote
        if evicted:
            local_floor = None
            remote_floor = None

        if not added and not evicted:
            return self

        return replace(
            self,
            seen_vacancy_ids=tuple(seen),
            pagination_floor_local=local_floor,
            pagination_floor_remote=remote_floor,
        )

    def with_chat_id(self, chat_id: int) -> "BotState":
        return replace(self, chat_id=chat_id)

    def with_polling_enabled(self, enabled: bool) -> "BotState":
        return replace(self, polling_enabled=enabled)

    def with_pagination_floor(
        self,
        branch: BranchName,
        floor: str | None,
    ) -> "BotState":
        if branch == "local":
            return replace(self, pagination_floor_local=floor)
        return replace(self, pagination_floor_remote=floor)


@dataclass(frozen=True, slots=True)
class StartCommandResult:
    accepted: bool
    message: str | None
    vacancies: tuple[VacancySummary, ...] = ()


@dataclass(frozen=True, slots=True)
class StopCommandResult:
    accepted: bool
    message: str
