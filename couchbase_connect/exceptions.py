"""Connect-level exceptions."""

from __future__ import annotations


class ConnectError(RuntimeError):
    """Base error for couchbase-connect operations."""


class ClusterCreateError(ConnectError):
    """Cluster creation or bootstrap failed."""


class NotConnectedError(ConnectError):
    """Operation requires an active connection."""


class SoftConnectFailure(ConnectError):
    """Connection failed but soft_failure mode absorbed the error."""
