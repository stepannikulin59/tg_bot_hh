from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .config import AppConfig
from .filters import (
    merge_and_sort_vacancies,
    page_stop_decision,
    text_has_keyword,
    title_has_keyword,
)
from .hh_client import HHClient, HHUnavailableError
from .models import (
    MAX_VACANCY_SEARCH_DEPTH,
    BotState,
    BranchName,
    SearchPage,
    StartCommandResult,
    StopCommandResult,
    VacancyDetails,
    VacancySummary,
    parse_hh_datetime,
)
from .state import StateStore

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RequestBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise RuntimeError("HH request budget exhausted")
        self.used += 1

    @property
    def available(self) -> bool:
        return self.used < self.limit


@dataclass(frozen=True, slots=True)
class BranchFetchResult:
    branch: BranchName
    vacancies: tuple[VacancySummary, ...]
    min_published_at_raw: str | None
    requested_any_page: bool


class VacancyBotService:
    def __init__(
        self,
        *,
        config: AppConfig,
        client: HHClient,
        state_store: StateStore,
        area_id: str | None = None,
        remote_schedule_id: str | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.state_store = state_store
        self.area_id = area_id
        self.remote_schedule_id = remote_schedule_id
        self._lookup_init_lock: asyncio.Lock | None = None

    @classmethod
    async def build(
        cls,
        *,
        config: AppConfig,
        client: HHClient | None = None,
        state_store: StateStore | None = None,
    ) -> "VacancyBotService":
        hh_client = client or HHClient(
            base_url=config.hh_base_url,
            user_agent=config.hh_user_agent,
            timeout_seconds=config.http_timeout_seconds,
        )
        store = state_store or StateStore(config.state_path)
        return cls(
            config=config,
            client=hh_client,
            state_store=store,
        )

    async def handle_start(self, chat_id: int) -> StartCommandResult:
        state = self.state_store.load()
        if state.chat_id is not None and state.chat_id != chat_id:
            return StartCommandResult(
                accepted=False,
                message=(
                    "Бот персональный и уже привязан "
                    "к другому чату."
                ),
            )

        previous_state = state
        state = state.with_chat_id(chat_id).with_polling_enabled(True)
        self.state_store.save(state)

        try:
            vacancies, _ = await self._collect_matching_vacancies(
                state=state,
                budget=RequestBudget(self.config.hh_request_limit_per_cycle),
                update_floors=False,
            )
        except HHUnavailableError:
            raise
        except Exception:
            self.state_store.save(previous_state)
            raise

        selected = vacancies[:10]
        state = state.with_seen_vacancies([item.vacancy_id for item in selected])
        self.state_store.save(state)

        return StartCommandResult(
            accepted=True,
            message=None,
            vacancies=tuple(selected),
        )

    async def handle_stop(self, chat_id: int) -> StopCommandResult:
        state = self.state_store.load()
        if state.chat_id != chat_id:
            return StopCommandResult(
                accepted=False,
                message=(
                    "Останавливать автоопрос может только "
                    "владелец этого бота."
                ),
            )

        self.state_store.save(state.with_polling_enabled(False))
        return StopCommandResult(
            accepted=True,
            message=(
                "Автоопрос остановлен до "
                "следующего /start."
            ),
        )

    async def run_poll_cycle(self) -> tuple[VacancySummary, ...]:
        state = self.state_store.load()
        if state.chat_id is None or not state.polling_enabled:
            return ()

        vacancies, state = await self._collect_matching_vacancies(
            state=state,
            budget=RequestBudget(self.config.hh_request_limit_per_cycle),
            update_floors=True,
        )

        seen_ids = set(state.seen_vacancy_ids)
        unseen = tuple(item for item in vacancies if item.vacancy_id not in seen_ids)
        if unseen:
            state = state.with_seen_vacancies([item.vacancy_id for item in unseen])

        self.state_store.save(state)
        return unseen

    async def _collect_matching_vacancies(
        self,
        *,
        state: BotState,
        budget: RequestBudget,
        update_floors: bool,
    ) -> tuple[tuple[VacancySummary, ...], BotState]:
        await self._ensure_search_filters()
        details_cache: dict[str, VacancyDetails] = {}

        local_result = await self._fetch_branch(
            branch="local",
            state=state,
            budget=budget,
            details_cache=details_cache,
        )
        remote_result = await self._fetch_branch(
            branch="remote",
            state=state,
            budget=budget,
            details_cache=details_cache,
        )

        merged = merge_and_sort_vacancies(
            local_result.vacancies,
            remote_result.vacancies,
        )
        if update_floors:
            if local_result.requested_any_page:
                state = state.with_pagination_floor(
                    "local",
                    local_result.min_published_at_raw,
                )
            if remote_result.requested_any_page:
                state = state.with_pagination_floor(
                    "remote",
                    remote_result.min_published_at_raw,
                )

        return merged, state

    async def _ensure_search_filters(self) -> None:
        if self.area_id is not None and self.remote_schedule_id is not None:
            return

        if self._lookup_init_lock is None:
            self._lookup_init_lock = asyncio.Lock()

        async with self._lookup_init_lock:
            if self.area_id is None:
                self.area_id = await self.client.resolve_area_id(
                    self.config.target_area_name
                )
            if self.remote_schedule_id is None:
                self.remote_schedule_id = await self.client.resolve_remote_schedule_id()

    async def _fetch_branch(
        self,
        *,
        branch: BranchName,
        state: BotState,
        budget: RequestBudget,
        details_cache: dict[str, VacancyDetails],
    ) -> BranchFetchResult:
        page = 0
        matched: list[VacancySummary] = []
        min_published_at_raw: str | None = None
        requested_any_page = False

        seen_ids = set(state.seen_vacancy_ids)
        floor = (
            state.pagination_floor_local
            if branch == "local"
            else state.pagination_floor_remote
        )
        if branch == "local":
            if self.area_id is None:
                raise RuntimeError("local area id is not initialized")
            area_id = self.area_id
            schedule_id = None
        else:
            if self.remote_schedule_id is None:
                raise RuntimeError("remote schedule id is not initialized")
            area_id = None
            schedule_id = self.remote_schedule_id

        while (
            budget.available
            and page * self.config.page_size < MAX_VACANCY_SEARCH_DEPTH
        ):
            budget.consume()
            requested_any_page = True
            search_page = await self.client.search_vacancies(
                page=page,
                per_page=self.config.page_size,
                area_id=area_id,
                schedule_id=schedule_id,
            )
            if not search_page.items:
                break

            page_min_raw = min(
                search_page.items,
                key=lambda item: item.published_at,
            ).published_at_raw
            if min_published_at_raw is None:
                min_published_at_raw = page_min_raw
            elif parse_hh_datetime(page_min_raw) < parse_hh_datetime(
                min_published_at_raw
            ):
                min_published_at_raw = page_min_raw

            matched.extend(
                await self._select_matching_vacancies(
                    search_page=search_page,
                    budget=budget,
                    details_cache=details_cache,
                )
            )

            decision = page_stop_decision(search_page.items, seen_ids, floor)
            if decision.all_seen or decision.floor_reached_without_new:
                break
            page += 1

        if page * self.config.page_size >= MAX_VACANCY_SEARCH_DEPTH:
            LOGGER.warning(
                "Stopping %s branch due to hh pagination depth limit",
                branch,
            )

        return BranchFetchResult(
            branch=branch,
            vacancies=tuple(matched),
            min_published_at_raw=min_published_at_raw,
            requested_any_page=requested_any_page,
        )

    async def _select_matching_vacancies(
        self,
        *,
        search_page: SearchPage,
        budget: RequestBudget,
        details_cache: dict[str, VacancyDetails],
    ) -> list[VacancySummary]:
        matched: list[VacancySummary] = []

        for vacancy in search_page.items:
            if title_has_keyword(vacancy.name):
                matched.append(vacancy)
                continue

            if text_has_keyword(vacancy.name, vacancy.snippet_text):
                matched.append(vacancy)
                continue

            details = details_cache.get(vacancy.vacancy_id)
            if details is None:
                if not budget.available:
                    break
                budget.consume()
                details = await self.client.get_vacancy_details(vacancy.vacancy_id)
                details_cache[vacancy.vacancy_id] = details

            if text_has_keyword(vacancy.name, details.description):
                matched.append(vacancy)

        return matched
