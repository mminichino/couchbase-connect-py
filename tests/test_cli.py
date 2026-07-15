"""Integration test exercising the cbctl CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from couchbase_connect import CouchbaseConfig, Server
from couchbase_connect.cli import app

pytestmark = [pytest.mark.server, pytest.mark.usefixtures("server_container")]

HOST = "127.0.0.1"
ADMIN = CouchbaseConfig.DEFAULT_USER
PASSWORD = CouchbaseConfig.DEFAULT_PASSWORD
BUCKET = "cli-test"
SCOPE = "cli_scope"
COLLECTION = "cli_collection"

runner = CliRunner()


def test_cli_create_cluster_bucket_scope_collection() -> None:
    cluster_result = runner.invoke(
        app,
        [
            "cluster",
            "create",
            "--host",
            HOST,
            "--username",
            ADMIN,
            "--password",
            PASSWORD,
            "--ram",
            "4",
            "--services",
            "data,index,query,fts",
            "--no-ssl",
        ],
    )
    assert cluster_result.exit_code == 0, cluster_result.output
    assert "Cluster created" in cluster_result.output

    bucket_result = runner.invoke(
        app,
        [
            "bucket",
            "create",
            BUCKET,
            "--host",
            HOST,
            "--username",
            ADMIN,
            "--password",
            PASSWORD,
            "--quota",
            "128",
            "--replicas",
            "0",
            "--no-ssl",
        ],
    )
    assert bucket_result.exit_code == 0, bucket_result.output
    assert f"Bucket {BUCKET!r} created" in bucket_result.output

    scope_result = runner.invoke(
        app,
        [
            "scope",
            "create",
            SCOPE,
            "--bucket",
            BUCKET,
            "--host",
            HOST,
            "--username",
            ADMIN,
            "--password",
            PASSWORD,
            "--no-ssl",
        ],
    )
    assert scope_result.exit_code == 0, scope_result.output
    assert f"Scope {SCOPE!r} created" in scope_result.output

    collection_result = runner.invoke(
        app,
        [
            "collection",
            "create",
            COLLECTION,
            "--bucket",
            BUCKET,
            "--scope",
            SCOPE,
            "--host",
            HOST,
            "--username",
            ADMIN,
            "--password",
            PASSWORD,
            "--no-ssl",
        ],
    )
    assert collection_result.exit_code == 0, collection_result.output
    assert f"Collection {COLLECTION!r} created" in collection_result.output

    db = Server.get_instance()
    config = (
        CouchbaseConfig()
        .host(HOST)
        .with_username(ADMIN)
        .with_password(PASSWORD)
        .ssl(False)
    )
    db.connect(config)
    assert db.is_bucket(BUCKET)
    assert db.collection_exists(BUCKET, SCOPE, COLLECTION)
    db.disconnect()
