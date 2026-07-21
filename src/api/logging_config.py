"""Structured key=value logging setup, suitable for CloudWatch ingestion."""

import logging

from src.api.correlation import CorrelationIdFilter

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "correlation_id",
}


class KeyValueFormatter(logging.Formatter):
    """Renders log records as timestamp=... level=... logger=... message=... k=v ..."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"timestamp={self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z')} "
            f"level={record.levelname} "
            f"logger={record.name} "
            f"correlation_id={getattr(record, 'correlation_id', '-')} "
            f"message={record.getMessage()!r}"
        )
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED
        }
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += " " + self.formatException(record.exc_info).replace("\n", " | ")
        return base


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a key=value StreamHandler to the root logger. Call once at startup."""
    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter())
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
