"""Unit tests for cluster connectivity test helpers."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from couchbase_connect.cli import _resolve_network_option, app
from couchbase_connect.config import CouchbaseConfig


def test_with_network_maps_internal_to_default() -> None:
    config = CouchbaseConfig().with_network("internal")
    assert config.network == "default"


def test_with_network_accepts_external_and_clears_auto() -> None:
    config = CouchbaseConfig().with_network("external")
    assert config.network == "external"
    assert config.with_network("auto").network is None
    assert CouchbaseConfig().with_network(None).network is None


def test_with_network_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid network"):
        CouchbaseConfig().with_network("lan")


def test_from_mapping_sets_network() -> None:
    config = CouchbaseConfig().from_mapping(
        {CouchbaseConfig.COUCHBASE_NETWORK: "external"}
    )
    assert config.network == "external"


def test_resolve_network_option_mutual_exclusion() -> None:
    assert _resolve_network_option(external=True, internal=False) == "external"
    assert _resolve_network_option(external=False, internal=True) == "default"
    assert _resolve_network_option(external=False, internal=False) is None
    with pytest.raises(typer.BadParameter):
        _resolve_network_option(external=True, internal=True)


def test_cluster_test_rejects_both_network_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "cluster",
            "test",
            "--host",
            "127.0.0.1",
            "--external",
            "--internal",
            "--no-ssl",
        ],
    )
    assert result.exit_code != 0
    assert "either --external or --internal" in result.output


def test_run_cluster_connectivity_test_uses_existing_bucket() -> None:
    from unittest.mock import MagicMock

    from couchbase_connect.cli import (
        TEST_DOCUMENT,
        TEST_DOCUMENT_ID,
        _run_cluster_connectivity_test,
    )

    db = MagicMock()
    db.is_bucket.return_value = True
    db.get.return_value = TEST_DOCUMENT

    _run_cluster_connectivity_test(db, bucket="existing")

    db.create_bucket.assert_not_called()
    db.drop_bucket.assert_not_called()
    db.connect_keyspace.assert_called_with("existing", "_default", "_default")
    db.upsert.assert_called_with(TEST_DOCUMENT_ID, TEST_DOCUMENT)
    db.get.assert_called_with(TEST_DOCUMENT_ID)


def test_run_cluster_connectivity_test_manages_temp_bucket() -> None:
    from unittest.mock import MagicMock

    from couchbase_connect.cli import (
        TEST_BUCKET,
        TEST_DOCUMENT,
        _run_cluster_connectivity_test,
    )

    db = MagicMock()
    db.is_bucket.return_value = False
    db.get.return_value = TEST_DOCUMENT

    _run_cluster_connectivity_test(db)

    db.create_bucket.assert_called_once()
    db.drop_bucket.assert_called_with(TEST_BUCKET)
    db.connect_keyspace.assert_called_with(TEST_BUCKET, "_default", "_default")
