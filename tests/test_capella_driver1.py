"""Integration tests mirroring Java CapellaDriver1Test."""

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

PROPERTY_FILE = "test.capella.1.properties"
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
def test_run(properties: dict[str, str]) -> None:
    username = properties.get(CouchbaseConfig.COUCHBASE_USER, CouchbaseConfig.DEFAULT_USER)
    password = properties.get(
        CouchbaseConfig.COUCHBASE_PASSWORD, CouchbaseConfig.DEFAULT_PASSWORD
    )
    bucket = properties.get(CouchbaseConfig.COUCHBASE_BUCKET, "test")
    scope = properties.get(CouchbaseConfig.COUCHBASE_SCOPE, "test")
    collection = properties.get(CouchbaseConfig.COUCHBASE_COLLECTION, "userdata")
    project = properties.get(CouchbaseConfig.CAPELLA_PROJECT_NAME, "junit")
    database = properties.get(CouchbaseConfig.CAPELLA_DATABASE_NAME, "testdb")
    user_id = properties.get(CouchbaseConfig.CAPELLA_USER_ID)
    token = properties.get(CouchbaseConfig.CAPELLA_TOKEN)

    logger.info("username: %s", username)

    db = Capella.get_instance()
    config = (
        CouchbaseConfig()
        .with_username(username)
        .with_password(password)
        .project(project)
        .database(database)
        .token(token or "")
    )
    if user_id:
        config.user_id(user_id)
    db.connect(config)

    result = db.is_bucket(bucket)
    logger.debug("isBucket: %s", result)
    db.create_bucket(bucket)
    assert db.is_bucket(bucket)
    db.create_scope(bucket, scope)
    db.create_collection(bucket, scope, collection)
    db.cluster_wait()
    db.create_primary_index(bucket, scope, collection)
    db.create_secondary_index(
        "idx_test",
        ["data"],
        bucket_name=bucket,
        scope_name=scope,
        collection_name=collection,
    )
    db.connect_bucket(bucket)
    db.connect_collection(scope, collection)
    db.upsert("doc::1", {"data": 1})
    db.drop_bucket(bucket)
    db.disconnect()


@pytest.mark.order(3)
def test_drop_cluster(properties: dict[str, str]) -> None:
    api = CouchbaseCapella.from_properties(properties)
    organization = CapellaOrganization.get_instance(api)
    project = CapellaProject.get_instance(organization)
    cluster = project.create_cluster(ClusterConfig())
    cluster.delete()
