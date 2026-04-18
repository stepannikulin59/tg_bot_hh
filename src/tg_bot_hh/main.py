from __future__ import annotations

import logging
import os
import re

from telegram import Update

from .config import AppConfig
from .telegram_app import build_application


class RedactingFilter(logging.Filter):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token.strip()
        self._token_pattern = (
            re.compile(re.escape(self._token))
            if self._token
            else None
        )
        self._bot_url_pattern = (
            re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+")
            if self._token
            else None
        )

    def _redact(self, value: str) -> str:
        redacted = value
        if self._bot_url_pattern is not None:
            redacted = self._bot_url_pattern.sub(r"\1<redacted>", redacted)
        if self._token_pattern is not None:
            redacted = self._token_pattern.sub("<redacted>", redacted)
        return redacted

    def filter(self, record: logging.LogRecord) -> bool:
        return True


class RedactingFormatter(logging.Formatter):
    def __init__(self, token: str, fmt: str) -> None:
        super().__init__(fmt=fmt)
        self._token = token.strip()
        self._token_pattern = (
            re.compile(re.escape(self._token))
            if self._token
            else None
        )
        self._bot_url_pattern = re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+")

    def _redact(self, value: str) -> str:
        redacted = self._bot_url_pattern.sub(r"\1<redacted>", value)
        if self._token_pattern is not None:
            redacted = self._token_pattern.sub("<redacted>", redacted)
        return redacted

    def format(self, record: logging.LogRecord) -> str:
        return self._redact(super().format(record))


def configure_logging(level_name: str) -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format=fmt,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if token:
        redactor = RedactingFilter(token=token)
        formatter = RedactingFormatter(token=token, fmt=fmt)
        root_logger = logging.getLogger()
        root_logger.addFilter(redactor)
        for handler in root_logger.handlers:
            handler.addFilter(redactor)
            handler.setFormatter(formatter)


def main() -> int:
    config = AppConfig.from_env()
    configure_logging(config.log_level)
    config.state_path.parent.mkdir(parents=True, exist_ok=True)

    application = build_application(config)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
