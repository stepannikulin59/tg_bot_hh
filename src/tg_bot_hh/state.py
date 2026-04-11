from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .models import BotState


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> BotState:
        if not self.path.exists():
            return BotState()

        data = json.loads(self.path.read_text(encoding="utf-8"))
        return BotState(
            chat_id=data.get("chat_id"),
            polling_enabled=data.get("polling_enabled", False),
            seen_vacancy_ids=tuple(data.get("seen_vacancy_ids", [])),
            pagination_floor_local=data.get("pagination_floor_local"),
            pagination_floor_remote=data.get("pagination_floor_remote"),
            schema_version=data.get("schema_version", 1),
        )

    def save(self, state: BotState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        payload["seen_vacancy_ids"] = list(state.seen_vacancy_ids)

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f"{self.path.name}.",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)

        os.replace(tmp_path, self.path)


def add_seen_vacancy_id(state: BotState, vacancy_id: str) -> BotState:
    return state.with_seen_vacancies([vacancy_id])
