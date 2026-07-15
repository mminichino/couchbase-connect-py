"""Pytest fixtures for Server and Capella integration tests."""

from __future__ import annotations

from typing import Dict, Iterator

import pytest

from couchbase_connect import cluster_create
from couchbase_connect.config import CouchbaseConfig
from couchbase_connect.server import Server
from helpers import load_properties
from couchbase_server_container import start_dedicated_container, stop_container


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


@pytest.fixture
def server_container():
    """Fresh Couchbase container for a single test; torn down afterwards."""
    name = start_dedicated_container()
    try:
        yield name
    finally:
        stop_container(name)


@pytest.fixture
def initialized_server_cluster(
    server_properties: Dict[str, str],
    server_container,
):
    """Initialize a fresh cluster for the current test."""
    hostname = server_properties.get(
        CouchbaseConfig.COUCHBASE_HOST, CouchbaseConfig.DEFAULT_HOSTNAME
    )
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
    endpoint = cluster_create.ClusterRestEndpoint.for_server(hostname, False)
    db = Server.get_instance()
    db.create_cluster(config, options)
    cluster_create.wait_for_cluster_services(endpoint, config.username, config.password)
    cluster_create.wait_for_query_ready(endpoint, config.username, config.password)
    cluster_create.wait_for_rebalance_complete(
        endpoint, config.username, config.password
    )
    db.disconnect()
    return server_container
