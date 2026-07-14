"""Capella API exceptions."""

from __future__ import annotations

from typing import Any, Optional


class CapellaAPIError(Exception):
    """Raised when a Capella REST call fails."""

    def __init__(
        self,
        code: int,
        body: Any,
        message: str,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.code = code
        self.body = body
        self.message = message
        self.cause = cause
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


class CapellaNotFoundError(Exception):
    """Raised when a Capella resource cannot be found."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UserNotConfiguredError(Exception):
    """Raised when Capella user email/id has not been configured."""

    def __init__(self, message: str = "Capella user not configured") -> None:
        self.message = message
        super().__init__(message)
