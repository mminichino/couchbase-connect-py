"""Retry helpers."""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_fixed,
    wait_incrementing,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

RETRYABLE_INDEX_ERROR_TYPES = (
    "ServiceUnavailableException",
    "AmbiguousTimeoutException",
    "UnAmbiguousTimeoutException",
    "TimeoutException",
    "RequestCanceledException",
    "TemporaryFailureException",
)

RETRYABLE_INDEX_ERROR_MESSAGES = (
    "rebalance in progress",
    "keyspace not found",
    "indexing.error",
    "query service is not available",
    "service unavailable",
    "channel_closed",
    "no_more_retries",
    "endpoint_not_available",
)


def is_retryable_index_error(error: BaseException) -> bool:
    type_name = type(error).__name__
    if type_name in RETRYABLE_INDEX_ERROR_TYPES:
        return True
    message = str(error).lower()
    return any(needle in message for needle in RETRYABLE_INDEX_ERROR_MESSAGES)


def linear_retry(
    attempts: int = 10,
    wait_factor_ms: int = 100,
) -> Callable[[F], F]:
    start = wait_factor_ms / 1000.0
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_incrementing(start=start, increment=start),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
    )


def index_creation_retry(
    attempts: int = 30,
    wait_seconds: float = 2.0,
) -> Callable[[F], F]:
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_fixed(wait_seconds),
        retry=retry_if_exception(is_retryable_index_error),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
    )


def before_wait_cluster_ready(retry_state: Any) -> None:
    if not retry_state.args:
        return
    owner = retry_state.args[0]
    wait = getattr(owner, "wait_for_cluster_operations_ready", None)
    if callable(wait):
        wait()


def with_index_creation_retry(
    attempts: int = 30,
    wait_seconds: float = 2.0,
) -> Callable[[F], F]:
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_fixed(wait_seconds),
        retry=retry_if_exception(is_retryable_index_error),
        before=before_wait_cluster_ready,
        before_sleep=before_sleep_log(logger, logging.DEBUG),
    )
