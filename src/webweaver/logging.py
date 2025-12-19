"""Logging utilities."""

from __future__ import annotations

import contextlib
import contextvars
import logging
from typing import Any

from rich.logging import RichHandler


_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("webweaver_run_id", default="-")
_step_var: contextvars.ContextVar[str] = contextvars.ContextVar("webweaver_step", default="-")


class _ContextFilter(logging.Filter):
    """Inject run context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.run_id = _run_id_var.get()  # type: ignore[attr-defined]
        record.step = _step_var.get()  # type: ignore[attr-defined]
        return True


@contextlib.contextmanager
def run_context(*, run_id: str, step: str | None = None) -> Any:
    """Temporarily bind run context for structured logging.

    Args:
        run_id: Run identifier.
        step: Optional step identifier.
    """

    token_run = _run_id_var.set(run_id)
    token_step = _step_var.set(step or _step_var.get())
    try:
        yield
    finally:
        _run_id_var.reset(token_run)
        _step_var.reset(token_step)


def set_step(step: str) -> None:
    """Update current step in context."""

    _step_var.set(step)


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging.

    Args:
        level: Logging level name.
    """

    handler = RichHandler(rich_tracebacks=True, show_time=True, show_level=True)
    handler.addFilter(_ContextFilter())

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s run=%(run_id)s step=%(step)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if configure_logging is called multiple times
    if not any(isinstance(h, RichHandler) for h in root.handlers):
        root.addHandler(handler)
    else:
        # Ensure existing rich handlers also have our filter/formatter
        for h in root.handlers:
            if isinstance(h, RichHandler):
                h.addFilter(_ContextFilter())
                h.setFormatter(formatter)


def get_logger(name: str) -> logging.Logger:
    """Get a module logger."""

    return logging.getLogger(name)


def log_exception(logger: logging.Logger, msg: str, **context: Any) -> None:
    """Log an exception with optional structured context."""

    if context:
        logger.exception("%s | context=%s", msg, context)
    else:
        logger.exception("%s", msg)
