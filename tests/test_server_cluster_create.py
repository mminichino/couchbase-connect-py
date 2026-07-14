"""Integration test mirroring Java ServerClusterCreateTest."""

from __future__ import annotations

import pytest

from couchbase_connect import CouchbaseConfig, Server

pytestmark = [pytest.mark.server, pytest.mark.usefixtures("shared_server_container")]

HOST = "127.0.0.1"
ADMIN = CouchbaseConfig.DEFAULT_USER
PASSWORD = CouchbaseConfig.DEFAULT_PASSWORD
BUCKET = "cluster-test"


def test_create_cluster_connect_and_create_bucket() -> None:
    db = Server.get_instance()
    config = (
        CouchbaseConfig()
        .host(HOST)
        .with_username(ADMIN)
        .with_password(PASSWORD)
        .bucket(BUCKET)
        .ssl(False)
    )
    options = {
        "couchbase.server.0.ip": HOST,
        "couchbase.server.0.ram": "4",
        "couchbase.server.0.services": "data,index,query,fts",
    }

    db.create_cluster(config, options)
    db.connect(config)

    # Drop leftovers so the requested quota fits a small single-node cluster.
    for name in list(db.list_buckets()):
        if name in {BUCKET, "data", "tmpidx", "default", "test"}:
            db.drop_bucket(name)

    db.create_bucket(BUCKET, 128, 0)
    assert db.is_bucket(BUCKET)
    db.drop_bucket(BUCKET)
    db.disconnect()
