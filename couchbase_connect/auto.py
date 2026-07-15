"""Facade that routes to Server or Capella based on CouchbaseConfig."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from couchbase_connect.config import CouchbaseConfig
from couchbase_connect.protocol import CouchbaseConnect, resolve


class AutoCouchbaseConnect:

    _instance: Optional["AutoCouchbaseConnect"] = None

    def __init__(self) -> None:
        self._delegate: Optional[CouchbaseConnect] = None

    @classmethod
    def get_instance(cls) -> "AutoCouchbaseConnect":
        if cls._instance is None:
            cls._instance = cls()
        assert cls._instance is not None
        return cls._instance

    def _require_delegate(self) -> CouchbaseConnect:
        if self._delegate is None:
            raise IllegalStateError(
                "Call connect(CouchbaseConfig) or create_cluster(CouchbaseConfig) first"
            )
        return self._delegate

    def _assign_delegate(self, config: CouchbaseConfig) -> None:
        self._delegate = resolve(config)

    def connect(self, config: CouchbaseConfig) -> None:
        self._assign_delegate(config)
        assert self._delegate is not None
        self._delegate.connect(config)

    def create_cluster(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._assign_delegate(config)
        assert self._delegate is not None
        self._delegate.create_cluster(config, options)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._require_delegate(), name)


class IllegalStateError(RuntimeError):
    pass
