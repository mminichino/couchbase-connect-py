"""Shared enums for couchbase-connect."""

from __future__ import annotations

from enum import Enum


class KeyStoreType(str, Enum):
    PKCS12 = "PKCS12"
    JKS = "JKS"


class TableType(str, Enum):
    RDBMS = "RDBMS"
    NOSQL = "NOSQL"
    COUCHBASE = "COUCHBASE"


class BucketTypeName(str, Enum):
    COUCHBASE = "couchbase"
    EPHEMERAL = "ephemeral"
    MEMCACHED = "memcached"


class StorageBackendName(str, Enum):
    COUCHSTORE = "couchstore"
    MAGMA = "magma"


class ConflictResolutionName(str, Enum):
    SEQUENCE_NUMBER = "seqno"
    TIMESTAMP = "lww"
    CUSTOM = "custom"
