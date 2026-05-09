from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _loguru_logger

from app.config import get_settings

_initialized = False


def _init_logger() -> None:
    global _initialized
    if _initialized:
        return

    settings = get_settings()
    log_level = settings.log_level.upper()

    # Remove default handler
    _loguru_logger.remove()

    # Console handler
    _loguru_logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[name]}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
        enqueue=True,
    )

    # File handler — rotating daily, kept for 30 days
    log_dir = Path("/app/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    _loguru_logger.add(
        str(log_dir / "financial_reports_{time:YYYY-MM-DD}.log"),
        level=log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{extra[name]} | "
            "{message}"
        ),
        rotation="00:00",
        retention="30 days",
        compression="gz",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    _initialized = True


def get_logger(name: str):
    """Return a loguru logger bound with the given name context."""
    _init_logger()
    return _loguru_logger.bind(name=name)
