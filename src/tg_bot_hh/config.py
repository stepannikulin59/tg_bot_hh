from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    telegram_bot_token: str
    hh_user_agent: str
    target_area_name: str
    state_path: Path
    poll_interval_seconds: int = 300
    hh_request_limit_per_cycle: int = 60
    log_level: str = "INFO"
    http_timeout_seconds: float = 30.0
    hh_base_url: str = "https://api.hh.ru"
    page_size: int = 100

    @classmethod
    def from_env(cls) -> "AppConfig":
        required = (
            "TELEGRAM_BOT_TOKEN",
            "HH_USER_AGENT",
            "TARGET_AREA_NAME",
            "STATE_PATH",
        )
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")

        return cls(
            telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
            hh_user_agent=os.environ["HH_USER_AGENT"],
            target_area_name=os.environ["TARGET_AREA_NAME"].strip(),
            state_path=Path(os.environ["STATE_PATH"]).expanduser(),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "300")),
            hh_request_limit_per_cycle=int(
                os.getenv("HH_REQUEST_LIMIT_PER_CYCLE", "60")
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "30")),
        )
