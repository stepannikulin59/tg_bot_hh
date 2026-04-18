from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .models import (
    TARGET_EXPERIENCE,
    TARGET_PROFESSIONAL_ROLE,
    Salary,
    SearchPage,
    VacancyDetails,
    VacancySummary,
    parse_hh_datetime,
)

LOGGER = logging.getLogger(__name__)


class HHClientError(RuntimeError):
    """Base hh client error."""


class HHUnavailableError(HHClientError):
    """Raised when hh.ru is temporarily unavailable."""


class HHForbiddenError(HHClientError):
    """Raised when hh.ru forbids access for current request profile."""


class AreaResolutionError(HHClientError):
    """Raised when a city cannot be resolved to a single leaf area."""


class HHClient:
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={
                "HH-User-Agent": user_agent,
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
        )
        self._max_retries = max_retries

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_dictionaries(self) -> dict[str, Any]:
        return await self._request_json("GET", "/dictionaries")

    async def get_professional_roles(self) -> dict[str, Any]:
        return await self._request_json("GET", "/professional_roles")

    async def resolve_remote_schedule_id(self) -> str:
        dictionaries = await self.get_dictionaries()
        for item in dictionaries.get("schedule", []):
            if item.get("id") == "remote":
                return "remote"
        raise HHClientError("schedule=remote is absent in /dictionaries")

    async def resolve_area_id(self, area_name: str) -> str:
        areas = await self._request_json("GET", "/areas")
        matches: list[str] = []
        stack = list(areas)
        target_name = area_name.strip().casefold()

        while stack:
            item = stack.pop()
            children = item.get("areas", [])
            if children:
                stack.extend(children)
                continue
            if item.get("name", "").strip().casefold() == target_name:
                matches.append(item["id"])

        if not matches:
            raise AreaResolutionError(
                f"Area '{area_name}' was not found among leaf nodes"
            )
        if len(matches) > 1:
            joined = ", ".join(matches)
            raise AreaResolutionError(
                f"Area '{area_name}' matched multiple leaf ids: {joined}"
            )
        return matches[0]

    async def search_vacancies(
        self,
        *,
        page: int,
        per_page: int,
        area_id: str | None,
        schedule_id: str | None,
    ) -> SearchPage:
        params: list[tuple[str, str | int]] = [
            ("page", page),
            ("per_page", per_page),
            ("professional_role", TARGET_PROFESSIONAL_ROLE),
            ("order_by", "publication_time"),
        ]
        params.extend(("experience", exp) for exp in TARGET_EXPERIENCE)

        if area_id is not None:
            params.append(("area", area_id))
        if schedule_id is not None:
            params.append(("schedule", schedule_id))

        payload = await self._request_json("GET", "/vacancies", params=params)
        items = tuple(
            self._parse_vacancy_summary(item) for item in payload.get("items", [])
        )
        return SearchPage(
            items=items,
            found=int(payload.get("found", 0)),
            page=int(payload.get("page", page)),
            pages=int(payload.get("pages", 0)),
            per_page=int(payload.get("per_page", per_page)),
        )

    async def get_vacancy_details(self, vacancy_id: str) -> VacancyDetails:
        payload = await self._request_json("GET", f"/vacancies/{vacancy_id}")
        return VacancyDetails(
            vacancy_id=str(payload["id"]),
            description=payload.get("description") or "",
            area_id=(payload.get("area") or {}).get("id"),
            area_name=(payload.get("area") or {}).get("name"),
            schedule_id=(payload.get("schedule") or {}).get("id"),
            work_format_ids=tuple(
                item["id"] for item in payload.get("work_format") or []
            ),
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str | int]] | None = None,
    ) -> Any:
        attempt = 0
        while True:
            try:
                response = await self._client.request(method, path, params=params)
            except httpx.HTTPError as exc:
                raise HHUnavailableError(
                    f"Failed to reach hh.ru for {method} {path}"
                ) from exc

            if response.status_code == 429 and attempt < self._max_retries:
                delay = 2**attempt
                LOGGER.warning(
                    "hh.ru returned 429 for %s %s; backing off %s seconds",
                    method,
                    path,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 403:
                    raise HHForbiddenError(
                        f"hh.ru rejected access for {method} {path}; status=403"
                    ) from exc
                if status_code == 429 or status_code == 408 or status_code >= 500:
                    raise HHUnavailableError(
                        f"hh.ru is unavailable for {method} {path}; status={status_code}"
                    ) from exc
                raise HHClientError(
                    f"hh.ru returned non-retryable status={status_code} "
                    f"for {method} {path}"
                ) from exc

            try:
                return response.json()
            except ValueError as exc:
                raise HHClientError(f"Invalid JSON in response for {method} {path}") from exc

    @staticmethod
    def _parse_vacancy_summary(item: dict[str, Any]) -> VacancySummary:
        salary_payload = item.get("salary") or item.get("salary_range")
        salary = None
        if salary_payload:
            salary = Salary(
                from_amount=(
                    salary_payload.get("from")
                    or salary_payload.get("from_amount")
                    or salary_payload.get("amount")
                ),
                to_amount=salary_payload.get("to") or salary_payload.get("to_amount"),
                currency=salary_payload.get("currency"),
            )

        snippet = item.get("snippet") or {}
        snippet_text = " ".join(
            part
            for part in (
                snippet.get("requirement"),
                snippet.get("responsibility"),
            )
            if part
        )

        published_at_raw = item["published_at"]
        return VacancySummary(
            vacancy_id=str(item["id"]),
            name=item["name"],
            employer_name=(
                (item.get("employer") or {}).get("name")
                or "Не указан"
            ),
            area_id=(item.get("area") or {}).get("id"),
            area_name=(item.get("area") or {}).get("name"),
            alternate_url=item["alternate_url"],
            published_at_raw=published_at_raw,
            published_at=parse_hh_datetime(published_at_raw),
            salary=salary,
            schedule_id=(item.get("schedule") or {}).get("id"),
            work_format_ids=tuple(part["id"] for part in item.get("work_format") or []),
            snippet_text=snippet_text,
        )
