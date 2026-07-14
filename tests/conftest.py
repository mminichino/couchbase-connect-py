"""Pytest fixtures for Server and Capella integration tests."""

from __future__ import annotations

import logging
from typing import Dict, Iterator

import pytest

from couchbase_connect import cluster_create
from couchbase_connect.config import CouchbaseConfig
from couchbase_connect.server import Server
from helpers import load_properties
from couchbase_server_container import shared_container

logger = logging.getLogger(__name__)

_cluster_ready = False


@pytest.fixture(scope="session")
def server_properties() -> Dict[str, str]:
    return load_properties("test.server.properties")


@pytest.fixture
def server_config(server_properties: Dict[str, str]) -> CouchbaseConfig:
    hostname = server_properties.get(
        CouchbaseConfig.COUCHBASE_HOST, CouchbaseConfig.DEFAULT_HOSTNAME
    )
    return (
        CouchbaseConfig()
        .from_mapping(server_properties)
        .host(hostname)
        .ssl(False)
    )


def _cleanup_test_buckets(config: CouchbaseConfig) -> None:
    """Drop leftover buckets from prior runs so RAM quotas stay available."""
    db = Server.get_instance()
    try:
        db.connect(config)
        for name in list(db.list_buckets()):
            if name in {"data", "cluster-test", "tmpidx", "default", "test"}:
                try:
                    db.drop_bucket(name)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("drop leftover bucket %s: %s", name, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("bucket cleanup skipped: %s", exc)
    finally:
        try:
            db.disconnect()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(autouse=True)
def _disconnect_server_after_test(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if request.node.get_closest_marker("server") is None:
        return
    try:
        Server.get_instance().disconnect()
    except Exception:  # noqa: BLE001
        pass
    # Ensure the next test does not reuse a broken SDK Cluster handle.
    Server._instance = None


@pytest.fixture(scope="session")
def shared_server_container():
    """Shared Couchbase container across the test session (Java sharedContainer)."""
    return shared_container()


@pytest.fixture(scope="session")
def initialized_server_cluster(
    server_properties: Dict[str, str],
    shared_server_container,
):
    """Initialize the shared cluster once (mirrors AbstractServerInitializedTest)."""
    global _cluster_ready
    if _cluster_ready:
        return shared_server_container

    hostname = server_properties.get(
        CouchbaseConfig.COUCHBASE_HOST, CouchbaseConfig.DEFAULT_HOSTNAME
    )
    username = server_properties.get(
        CouchbaseConfig.COUCHBASE_USER, CouchbaseConfig.DEFAULT_USER
    )
    password = server_properties.get(
        CouchbaseConfig.COUCHBASE_PASSWORD, CouchbaseConfig.DEFAULT_PASSWORD
    )
    endpoint = cluster_create.ClusterRestEndpoint.for_server(hostname, False)

    if cluster_create.is_cluster_initialized(endpoint, username, password):
        cluster_create.wait_for_cluster_services(endpoint, username, password)
        cluster_create.wait_for_query_ready(endpoint, username, password)
        cluster_create.wait_for_rebalance_complete(endpoint, username, password)
        _cluster_ready = True
        return shared_server_container

    config = (
        CouchbaseConfig()
        .from_mapping(server_properties)
        .host(hostname)
        .ssl(False)
    )
    options = {
        "couchbase.server.0.ip": hostname,
        "couchbase.server.0.ram": "4",
        "couchbase.server.0.services": "data,index,query,fts",
    }
    db = Server.get_instance()
    db.create_cluster(config, options)
    cluster_create.wait_for_cluster_services(endpoint, config.username, config.password)
    cluster_create.wait_for_query_ready(endpoint, config.username, config.password)
    cluster_create.wait_for_rebalance_complete(
        endpoint, config.username, config.password
    )
    db.disconnect()
    _cluster_ready = True
    _cleanup_test_buckets(config)
    return shared_server_container
