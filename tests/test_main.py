from __future__ import annotations

import io
import logging

from tg_bot_hh.main import RedactingFilter, RedactingFormatter


def test_logging_redaction_hides_telegram_token():
    token = "12345:ABCDE"
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter(token))
    handler.setFormatter(
        RedactingFormatter(
            token=token,
            fmt="%(levelname)s %(message)s",
        )
    )

    logger = logging.Logger("test-redaction", level=logging.INFO)
    logger.handlers = [handler]
    logger.propagate = False

    logger.info(
        "HTTP Request: POST https://api.telegram.org/bot%s/getMe",
        token,
    )

    output = stream.getvalue()
    assert token not in output
    assert "bot<redacted>/getMe" in output
