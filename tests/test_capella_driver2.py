"""Integration tests mirroring Java CapellaDriver2Test."""

from __future__ import annotations

import logging

import pytest

from couchbase_connect import Capella, CouchbaseConfig
from couchbase_connect.capella import (
    CapellaConnectivity,
    CapellaOrganization,
    CapellaProject,
    ClusterConfig,
    CouchbaseCapella,
)
from helpers import capella_properties_available, load_properties

logger = logging.getLogger(__name__)

PROPERTY_FILE = "test.capella.2.properties"
DEFAULT_CLUSTER_USER = "developer"
DEFAULT_CLUSTER_PASSWORD = "#C0uchBas3"

pytestmark = [
    pytest.mark.capella,
    pytest.mark.skipif(
        not capella_properties_available(PROPERTY_FILE),
        reason=f"Capella credentials file tests/resources/{PROPERTY_FILE} not configured",
    ),
]


@pytest.fixture(scope="module")
def properties() -> dict[str, str]:
    return load_properties(PROPERTY_FILE)


@pytest.mark.order(1)
def test_create_cluster(properties: dict[str, str]) -> None:
    username = properties.get(CouchbaseConfig.COUCHBASE_USER, DEFAULT_CLUSTER_USER)
    password = properties.get(
        CouchbaseConfig.COUCHBASE_PASSWORD, DEFAULT_CLUSTER_PASSWORD
    )
    api = CouchbaseCapella.from_properties(properties)
    organization = CapellaOrganization.get_instance(api)
    project = CapellaProject.get_instance(organization)
    cluster = project.create_cluster(ClusterConfig())
    assert cluster is not None
    allowed = cluster.get_allowed_cidr()
    assert allowed is not None
    allowed.create_allowed_cidr("0.0.0.0/0")
    credentials = cluster.get_credentials()
    assert credentials is not None
    credentials.create_credential(username, password, None)
    assert CapellaConnectivity().check_connectivity(
        cluster.get_connect_string() or "",
        timeout=120.0,
    )


@pytest.mark.order(2)
def test_basic1(properties: dict[str, str]) -> None:
    db = Capella.get_instance()
    config = CouchbaseConfig().from_mapping(properties)
    db.connect(config)

    result = db.is_bucket()
    logger.debug("isBucket: %s", result)
    db.create_bucket()
    assert db.is_bucket()
    db.create_scope()
    db.create_collection()
    db.cluster_wait()
    db.create_primary_index()
    db.create_secondary_index("idx_test", ["data"])
    db.connect_keyspace()
    db.upsert("doc::1", {"data": 1})
    db.drop_bucket()
    db.disconnect()


@pytest.mark.order(3)
def test_drop_cluster(properties: dict[str, str]) -> None:
    api = CouchbaseCapella.from_properties(properties)
    organization = CapellaOrganization.get_instance(api)
    project = CapellaProject.get_instance(organization)
    cluster = project.create_cluster(ClusterConfig())
    cluster.delete()
