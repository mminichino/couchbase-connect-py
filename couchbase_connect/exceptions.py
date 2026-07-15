"""Connect-level exceptions."""

from __future__ import annotations


class ConnectError(RuntimeError):
    pass


class ClusterCreateError(ConnectError):
    pass


class NotConnectedError(ConnectError):
    pass


class SoftConnectFailure(ConnectError):
    pass
