from __future__ import annotations

import logging

from telegram import Update

from .config import AppConfig
from .telegram_app import build_application


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    config = AppConfig.from_env()
    configure_logging(config.log_level)
    config.state_path.parent.mkdir(parents=True, exist_ok=True)

    application = build_application(config)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
