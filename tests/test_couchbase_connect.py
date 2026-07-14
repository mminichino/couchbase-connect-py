"""Unit tests mirroring Java CouchbaseConnectTest."""

from __future__ import annotations

import pytest

from couchbase_connect import (
    AutoCouchbaseConnect,
    Capella,
    CouchbaseConfig,
    Server,
    get_instance,
    resolve,
)
from couchbase_connect.auto import IllegalStateError
from helpers import load_properties


def test_resolve_capella_from_properties_file() -> None:
    properties = {
        "capella.token": "test-token",
        "capella.project.name": "junit",
        "capella.database.name": "testdb",
        "capella.user.id": "user-id",
        "couchbase.username": "developer",
        "couchbase.password": "password",
        "couchbase.bucket": "data",
    }
    config = CouchbaseConfig().from_mapping(properties)
    assert config.is_capella()
    assert resolve(config) is Capella.get_instance()


def test_resolve_server_from_properties_file() -> None:
    properties = load_properties("test.server.properties")
    config = CouchbaseConfig().from_mapping(properties)
    assert not config.is_capella()
    assert resolve(config) is Server.get_instance()


def test_get_instance_returns_auto_router() -> None:
    assert get_instance() is AutoCouchbaseConnect.get_instance()


def test_get_cluster_requires_connect_first() -> None:
    # Fresh Auto facade without a prior connect/create_cluster.
    AutoCouchbaseConnect._instance = None
    db = get_instance()
    with pytest.raises(IllegalStateError):
        db.get_cluster()
