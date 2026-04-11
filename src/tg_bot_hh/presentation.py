from __future__ import annotations

from datetime import datetime

from .models import Salary, VacancySummary

TELEGRAM_MESSAGE_LIMIT = 4096
DEFAULT_BATCH_SIZE = 10


def format_salary(salary: Salary | None) -> str | None:
    if salary is None:
        return None

    if salary.from_amount is not None and salary.to_amount is not None:
        return (
            f"{salary.from_amount}-{salary.to_amount} "
            f"{salary.currency or ''}"
        ).strip()
    if salary.from_amount is not None:
        return f"от {salary.from_amount} {salary.currency or ''}".strip()
    if salary.to_amount is not None:
        return f"до {salary.to_amount} {salary.currency or ''}".strip()
    return None


def format_vacancy_item(vacancy: VacancySummary, index: int) -> str:
    lines = [
        f"{index}. {vacancy.name}",
        f"Работодатель: {vacancy.employer_name}",
        f"Город/формат: {vacancy.area_name or 'Не указано'}",
    ]

    salary_text = format_salary(vacancy.salary)
    if salary_text:
        lines.append(f"Зарплата: {salary_text}")

    lines.append(f"Ссылка: {vacancy.alternate_url}")
    return "\n".join(lines)


def _compose_message(header: str, blocks: list[str]) -> str:
    if not blocks:
        return header
    return f"{header}\n\n" + "\n\n".join(blocks)


def _split_text_to_limit(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text

    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")

    if remaining:
        chunks.append(remaining)
    return chunks


def _pack_cards(
    *,
    header: str,
    cards: list[str],
    max_length: int,
) -> list[str]:
    messages: list[str] = []
    current_cards: list[str] = []

    for card in cards:
        candidate = _compose_message(header, [*current_cards, card])
        if len(candidate) <= max_length:
            current_cards.append(card)
            continue

        if current_cards:
            messages.append(_compose_message(header, current_cards))
            current_cards = []

        single = _compose_message(header, [card])
        if len(single) <= max_length:
            current_cards = [card]
            continue

        header_overhead = len(header) + 2
        if max_length <= header_overhead:
            raise ValueError("max_length is too small for message header")

        text_limit = max_length - header_overhead
        for chunk in _split_text_to_limit(card, text_limit):
            messages.append(_compose_message(header, [chunk]))

    if current_cards:
        messages.append(_compose_message(header, current_cards))

    return messages


def build_vacancy_messages(
    vacancies: tuple[VacancySummary, ...],
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_length: int = TELEGRAM_MESSAGE_LIMIT,
) -> list[str]:
    if not vacancies:
        return []

    timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    header = f"Вакансии на {timestamp}"

    messages: list[str] = []
    for start in range(0, len(vacancies), batch_size):
        batch = vacancies[start : start + batch_size]
        cards = [
            format_vacancy_item(vacancy, index=start + offset + 1)
            for offset, vacancy in enumerate(batch)
        ]
        messages.extend(_pack_cards(header=header, cards=cards, max_length=max_length))

    return messages
