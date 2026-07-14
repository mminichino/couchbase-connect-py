"""Integration test mirroring Java ServerDriver1Test."""

from __future__ import annotations

import logging

import pytest

from couchbase_connect import CouchbaseConfig, Server
from helpers import load_properties

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.server, pytest.mark.usefixtures("initialized_server_cluster")]


def test_run() -> None:
    properties = load_properties("test.server.properties")
    username = properties.get(
        CouchbaseConfig.COUCHBASE_USER, CouchbaseConfig.DEFAULT_USER
    )
    password = properties.get(
        CouchbaseConfig.COUCHBASE_PASSWORD, CouchbaseConfig.DEFAULT_PASSWORD
    )
    bucket = properties.get(CouchbaseConfig.COUCHBASE_BUCKET, "default")
    scope = properties.get(CouchbaseConfig.COUCHBASE_SCOPE, "_default")
    collection = properties.get(CouchbaseConfig.COUCHBASE_COLLECTION, "_default")
    hostname = properties.get(
        CouchbaseConfig.COUCHBASE_HOST, CouchbaseConfig.DEFAULT_HOSTNAME
    )

    logger.info("hostname: %s", hostname)
    logger.info("username: %s", username)

    db = Server.get_instance()
    config = (
        CouchbaseConfig()
        .from_mapping(properties)
        .host(hostname)
        .with_username(username)
        .with_password(password)
        .ssl(False)
    )
    db.connect(config)

    if db.is_bucket(bucket):
        db.drop_bucket(bucket)
    result = db.is_bucket(bucket)
    logger.debug("isBucket: %s", result)
    db.create_bucket(bucket, quota=128, replicas=0)
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
