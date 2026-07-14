"""Integration test mirroring Java ServerDriver2Test."""

from __future__ import annotations

import logging

import pytest

from couchbase_connect import CouchbaseConfig, Server
from helpers import load_properties

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.server, pytest.mark.usefixtures("initialized_server_cluster")]


def test_run() -> None:
    properties = load_properties("test.server.properties")
    hostname = properties.get(
        CouchbaseConfig.COUCHBASE_HOST, CouchbaseConfig.DEFAULT_HOSTNAME
    )
    db = Server.get_instance()
    config = (
        CouchbaseConfig()
        .from_mapping(properties)
        .host(hostname)
        .ssl(False)
    )
    db.connect(config)

    bucket = config.bucket_name
    if bucket and db.is_bucket(bucket):
        db.drop_bucket(bucket)
    result = db.is_bucket()
    logger.debug("isBucket: %s", result)
    db.create_bucket(quota=128, replicas=0)
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
