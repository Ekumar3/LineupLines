"""Correlation ID propagation for tracing a single poll cycle through logs."""

import logging
import uuid
from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


def new_correlation_id() -> str:
    """Generate a new correlation ID and set it as current, returning it."""
    cid = uuid.uuid4().hex[:8]
    correlation_id_var.set(cid)
    return cid


class CorrelationIdFilter(logging.Filter):
    """Injects the current correlation_id into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True
