"""结构化日志：structlog + 请求级 trace_id 贯穿。"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

_CONFIGURED = False


def init_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _CONFIGURED:
        init_logging()
    return structlog.get_logger(name)


def bind_trace(trace_id: str) -> None:
    clear_contextvars()
    bind_contextvars(trace_id=trace_id)
