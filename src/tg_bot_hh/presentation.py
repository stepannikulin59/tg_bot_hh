from __future__ import annotations

from datetime import datetime

from .models import Salary, VacancySummary

DEFAULT_BATCH_SIZE = 10


def format_salary(salary: Salary | None) -> str | None:
    if salary is None:
        return None
    if salary.from_amount is not None and salary.to_amount is not None:
        return f"{salary.from_amount}-{salary.to_amount} {salary.currency or ''}".strip()
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


def build_vacancy_messages(
    vacancies: tuple[VacancySummary, ...],
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_length: int = 4096,
) -> list[str]:
    del max_length
    if not vacancies:
        return []

    header = f"Вакансии на {(now or datetime.now()).strftime('%Y-%m-%d %H:%M')}"
    messages: list[str] = []
    for start in range(0, len(vacancies), batch_size):
        cards = [
            format_vacancy_item(vacancy, index=start + offset + 1)
            for offset, vacancy in enumerate(vacancies[start : start + batch_size])
        ]
        messages.append(f"{header}\n\n" + "\n\n".join(cards))
    return messages
