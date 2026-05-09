from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from typing import Any, Type, Tuple

from app.utils.logger import get_logger

logger = get_logger("retry")


def sync_retry(
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
):
    """
    Decorator for synchronous functions with exponential-backoff retry.

    Usage::

        @sync_retry(exceptions=(IOError, TimeoutError), max_attempts=5)
        def fetch_file(path):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise
                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    if jitter:
                        import random
                        delay *= 0.5 + random.random() * 0.5
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed "
                        f"({type(exc).__name__}: {exc}). Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
        return wrapper
    return decorator


def async_retry(
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
):
    """
    Decorator for async functions with exponential-backoff retry.

    Usage::

        @async_retry(exceptions=(httpx.HTTPError,), max_attempts=4)
        async def fetch_data(url):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {exc}"
                        )
                        raise
                    delay = min(base_delay * (exponential_base ** (attempt - 1)), max_delay)
                    if jitter:
                        import random
                        delay *= 0.5 + random.random() * 0.5
                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed "
                        f"({type(exc).__name__}: {exc}). Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
        return wrapper
    return decorator


class RetryContext:
    """
    Context-manager-style retry helper for use in procedural async code
    where a decorator is inconvenient.

    Example::

        async with RetryContext(max_attempts=3) as ctx:
            while await ctx.should_try():
                try:
                    result = await risky_operation()
                    break
                except SomeError as exc:
                    await ctx.record_failure(exc)
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exceptions: Tuple[Type[Exception], ...] = (Exception,),
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exceptions = exceptions
        self.attempt = 0
        self.last_exception: Exception | None = None

    async def __aenter__(self) -> "RetryContext":
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    async def should_try(self) -> bool:
        if self.attempt == 0:
            self.attempt = 1
            return True
        return self.attempt <= self.max_attempts

    async def record_failure(self, exc: Exception) -> None:
        self.last_exception = exc
        if self.attempt >= self.max_attempts:
            raise exc
        delay = min(self.base_delay * (2 ** (self.attempt - 1)), self.max_delay)
        logger.warning(f"Attempt {self.attempt}/{self.max_attempts} failed: {exc}. Sleeping {delay:.2f}s")
        self.attempt += 1
        await asyncio.sleep(delay)
