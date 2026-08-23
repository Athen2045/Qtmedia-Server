"""Minimal log redaction for private bot runtime values."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
BOT_TOKEN_PATTERN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")


def _redact_text(value: object, secrets: tuple[str, ...]) -> object:
    if not isinstance(value, str):
        return value
    redacted = value
    for secret in secrets:
        redacted = redacted.replace(secret, "[redacted-secret]")
    redacted = URL_PATTERN.sub("[redacted-url]", redacted)
    return BOT_TOKEN_PATTERN.sub("[redacted-secret]", redacted)


def _redact_argument(value: object, secrets: tuple[str, ...]) -> object:
    """Redact rendered objects such as ``httpx.URL`` without changing safe values."""

    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, (bytes, int, float, bool, type(None))):
        return value
    rendered = str(value)
    redacted = _redact_text(rendered, secrets)
    return redacted if redacted != rendered else value


class _PrivateLogRedactionFilter(logging.Filter):
    """Redact sensitive text before a handler formats a log record."""

    def __init__(self, secrets: Iterable[str]):
        super().__init__()
        self._secrets: tuple[str, ...] = ()
        self.add_secrets(secrets)

    def add_secrets(self, secrets: Iterable[str]) -> None:
        """Merge non-empty secrets without retaining duplicate values."""

        values = (*self._secrets, *(value for value in secrets if value))
        self._secrets = tuple(dict.fromkeys(values))

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_text(record.msg, self._secrets)
        if isinstance(record.args, Mapping):
            record.args = {
                key: _redact_argument(value, self._secrets)
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(
                _redact_argument(value, self._secrets) for value in record.args
            )
        else:
            record.args = _redact_argument(record.args, self._secrets)
        return True


def configure_private_logging(secret_values: tuple[str, ...]) -> None:
    """Attach an idempotent redaction filter to active root handlers."""

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root_logger.handlers:
        existing_filter = next(
            (
                item
                for item in handler.filters
                if isinstance(item, _PrivateLogRedactionFilter)
            ),
            None,
        )
        if existing_filter is None:
            handler.addFilter(_PrivateLogRedactionFilter(secret_values))
        else:
            existing_filter.add_secrets(secret_values)
