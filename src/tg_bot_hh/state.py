from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import BotState


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    chat_id INTEGER,
                    polling_enabled INTEGER NOT NULL,
                    seen_vacancy_ids_json TEXT NOT NULL,
                    pagination_floor_local TEXT,
                    pagination_floor_remote TEXT,
                    schema_version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load(self) -> BotState:
        if not self.path.exists():
            return BotState()

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    chat_id,
                    polling_enabled,
                    seen_vacancy_ids_json,
                    pagination_floor_local,
                    pagination_floor_remote,
                    schema_version
                FROM bot_state
                WHERE id = 1
                """
            ).fetchone()

        if row is None:
            return BotState()

        seen_json = row[2] or "[]"
        seen_ids = json.loads(seen_json)
        return BotState(
            chat_id=row[0],
            polling_enabled=bool(row[1]),
            seen_vacancy_ids=tuple(seen_ids),
            pagination_floor_local=row[3],
            pagination_floor_remote=row[4],
            schema_version=row[5] or 1,
        )

    def save(self, state: BotState) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        seen_json = json.dumps(list(state.seen_vacancy_ids), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_state (
                    id,
                    chat_id,
                    polling_enabled,
                    seen_vacancy_ids_json,
                    pagination_floor_local,
                    pagination_floor_remote,
                    schema_version,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    polling_enabled = excluded.polling_enabled,
                    seen_vacancy_ids_json = excluded.seen_vacancy_ids_json,
                    pagination_floor_local = excluded.pagination_floor_local,
                    pagination_floor_remote = excluded.pagination_floor_remote,
                    schema_version = excluded.schema_version,
                    updated_at = excluded.updated_at
                """,
                (
                    1,
                    state.chat_id,
                    int(state.polling_enabled),
                    seen_json,
                    state.pagination_floor_local,
                    state.pagination_floor_remote,
                    state.schema_version,
                    updated_at,
                ),
            )
            conn.commit()
