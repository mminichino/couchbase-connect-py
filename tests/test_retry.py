"""Unit tests for tenacity-based retry helpers."""

from __future__ import annotations

import pytest

from couchbase_connect.retry import (
    is_retryable_index_error,
    linear_retry,
    with_index_creation_retry,
)


def test_linear_retry_eventually_succeeds() -> None:
    calls = {"n": 0}

    @linear_retry(attempts=5, wait_factor_ms=1)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_linear_retry_exhausts_attempts() -> None:
    @linear_retry(attempts=3, wait_factor_ms=1)
    def always_fail() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        always_fail()


def test_index_creation_retry_skips_non_retryable() -> None:
    calls = {"n": 0}

    @with_index_creation_retry(attempts=5, wait_seconds=0.01)
    def fail_hard() -> None:
        calls["n"] += 1
        raise RuntimeError("permission denied")

    with pytest.raises(RuntimeError, match="permission denied"):
        fail_hard()
    assert calls["n"] == 1


def test_index_creation_retry_retries_retryable() -> None:
    calls = {"n": 0}

    class Owner:
        def wait_for_cluster_operations_ready(self) -> None:
            calls["wait"] = calls.get("wait", 0) + 1

        @with_index_creation_retry(attempts=5, wait_seconds=0.01)
        def create_index(self) -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("rebalance in progress")
            return "ready"

    assert Owner().create_index() == "ready"
    assert calls["n"] == 3
    assert calls["wait"] == 3


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Rebalance in Progress", True),
        ("Keyspace not found", True),
        ("boom", False),
    ],
)
def test_is_retryable_index_error(message: str, expected: bool) -> None:
    assert is_retryable_index_error(RuntimeError(message)) is expected
