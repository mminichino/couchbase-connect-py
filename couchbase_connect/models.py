"""Value objects used by connection automation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from couchbase_connect.enums import TableType


@dataclass
class BucketData:
    name: str = "default"
    type: str = "couchbase"
    quota: int = 128
    replicas: int = 1
    eviction: str = ""
    ttl: int = 0
    storage: str = "magma"
    resolution: str = "seqno"
    password: str = ""


@dataclass
class ScopeData:
    name: str = "_default"


@dataclass
class CollectionData:
    name: str = "_default"
    ttl: int = 0
    history: bool = False


@dataclass
class IndexData:
    column: str = ""
    table: str = ""
    name: str = ""
    index_keys: List[str] = field(default_factory=list)
    condition: str = ""
    num_replicas: int = -1
    is_primary: bool = False


@dataclass
class SearchIndexData:
    bucket: str = ""
    scope: str = ""
    name: str = ""
    type: str = ""
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoleData:
    role: str
    bucket_name: str = "*"
    scope_name: str = "*"
    collection_name: str = "*"


@dataclass
class UserData:
    id: str = ""
    password: Optional[str] = None
    name: str = ""
    email: str = ""
    groups: List[str] = field(default_factory=list)
    roles: List[RoleData] = field(default_factory=list)


@dataclass
class GroupData:
    id: str = ""
    description: str = ""
    roles: List[RoleData] = field(default_factory=list)


@dataclass
class TableData:
    name: str = ""
    type: TableType = TableType.COUCHBASE
    bucket: Optional[BucketData] = None
    password: str = ""
    scope: Optional[ScopeData] = None
    collection: Optional[CollectionData] = None
    indexes: List[IndexData] = field(default_factory=list)
    search_indexes: List[SearchIndexData] = field(default_factory=list)

    @staticmethod
    def in_list(tables: Sequence["TableData"], name: str) -> bool:
        return any(table.name == name for table in tables)


@dataclass
class ClusterNodeConfig:
    ip: str = "127.0.0.1"
    ram_gib: int = 8
    services: List[str] = field(default_factory=lambda: ["data", "index", "query", "fts"])


@dataclass
class CapellaNodeConfig:
    cpu: int = 4
    ram: int = 16
    services: List[str] = field(
        default_factory=lambda: ["data", "query", "index", "search"]
    )
