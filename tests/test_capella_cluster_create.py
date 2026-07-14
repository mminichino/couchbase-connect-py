"""Integration test mirroring Java CapellaClusterCreateTest."""

from __future__ import annotations

import logging

import pytest

from couchbase_connect import Capella, CouchbaseConfig
from helpers import capella_properties_available, load_properties

logger = logging.getLogger(__name__)

PROPERTY_FILE = "test.capella.2.properties"

pytestmark = [
    pytest.mark.capella,
    pytest.mark.skipif(
        not capella_properties_available(PROPERTY_FILE),
        reason=f"Capella credentials file tests/resources/{PROPERTY_FILE} not configured",
    ),
]


@pytest.fixture
def properties() -> dict[str, str]:
    return load_properties(PROPERTY_FILE)


@pytest.fixture
def db() -> Capella:
    instance = Capella.get_instance()
    yield instance
    try:
        instance.destroy_cluster()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to destroy Capella cluster during cleanup: %s", exc)
    try:
        instance.disconnect()
    except Exception:  # noqa: BLE001
        pass


def test_create_cluster_connect_create_bucket_and_destroy(
    properties: dict[str, str],
    db: Capella,
) -> None:
    config = CouchbaseConfig().from_mapping(properties)

    db.create_cluster(config)
    db.connect(config)

    bucket = config.bucket_name
    assert bucket is not None
    db.create_bucket(bucket, 128, 0)
    assert db.is_bucket(bucket)
    db.cluster_wait()

    db.drop_bucket(bucket)
    db.destroy_cluster()
    db.disconnect()
