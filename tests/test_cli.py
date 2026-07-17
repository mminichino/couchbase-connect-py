"""Integration test exercising the cbctl CLI."""

from __future__ import annotations

from pathlib import Path

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


def test_cli_create_cluster_bucket_scope_collection(tmp_path: Path) -> None:
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
            "--no-ssl",
        ],
    )
    assert cluster_result.exit_code == 0, cluster_result.output
    assert cluster_result.output.strip() == "Cluster already configured"

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

    exists_commands = [
        ["cluster", "exists"],
        ["bucket", "exists", BUCKET],
        ["scope", "exists", SCOPE, "--bucket", BUCKET],
        [
            "collection",
            "exists",
            COLLECTION,
            "--bucket",
            BUCKET,
            "--scope",
            SCOPE,
        ],
    ]
    for command in exists_commands:
        result = runner.invoke(
            app,
            [
                *command,
                "--host",
                HOST,
                "--username",
                ADMIN,
                "--password",
                PASSWORD,
                "--no-ssl",
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "true"

    json_lines = tmp_path / "documents.jsonl"
    json_lines.write_text('{"name":"one"}\n{"name":"two"}\n', encoding="utf-8")
    import_args = [
        "import",
        str(json_lines),
        f"{BUCKET}.{SCOPE}.{COLLECTION}",
        "--host",
        HOST,
        "--username",
        ADMIN,
        "--password",
        PASSWORD,
        "--no-ssl",
    ]
    import_result = runner.invoke(app, import_args)
    assert import_result.exit_code == 0, import_result.output
    assert "Imported 2 documents" in import_result.output

    import_result = runner.invoke(app, import_args)
    assert import_result.exit_code == 0, import_result.output
    assert "Collection not empty" in import_result.output

    auto_keyspace = "cli-import.auto_scope.auto_collection"
    import_args[2] = auto_keyspace
    import_result = runner.invoke(app, import_args)
    assert import_result.exit_code == 0, import_result.output
    assert "Imported 2 documents" in import_result.output

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
