"""Public connection protocol and factory helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Set,
    runtime_checkable, cast,
)

from couchbase.cluster import Cluster
from couchbase.collection import Collection
from couchbase.management.buckets import BucketType, StorageBackend
from couchbase.management.users import Role
from couchbase.scope import Scope

from couchbase_connect.config import CouchbaseConfig
from couchbase_connect.models import (
    BucketData,
    GroupData,
    IndexData,
    RoleData,
    SearchIndexData,
    TableData,
    UserData,
)


@runtime_checkable
class CouchbaseConnect(Protocol):

    def connect(self, config: CouchbaseConfig) -> None: ...

    def create_cluster(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]] = None,
    ) -> None: ...

    def destroy_cluster(self) -> None: ...

    def disconnect(self) -> None: ...

    def stream(
        self,
        bucket_name: str,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> Any: ...

    def host_value(self) -> str: ...

    def admin_user_value(self) -> str: ...

    def admin_password_value(self) -> str: ...

    def get_bucket_name(self) -> Optional[str]: ...

    def get_scope_name(self) -> Optional[str]: ...

    def get_collection_name(self) -> Optional[str]: ...

    def get_cluster(self) -> Optional[Cluster]: ...

    def get_bucket(self) -> Any: ...

    def get_scope(self) -> Optional[Scope]: ...

    def get_collection(self) -> Optional[Collection]: ...

    def get_keyspace(self) -> str: ...

    def get_index_node_count(self) -> int: ...

    def list_buckets(self) -> List[str]: ...

    def is_bucket(self, bucket: Optional[str] = None) -> bool: ...

    def cluster_wait(self) -> None: ...

    def cluster_ping(self) -> None: ...

    def connect_bucket(self, name: Optional[str] = None) -> None: ...

    def connect_scope(self, name: Optional[str] = None) -> None: ...

    def connect_collection(
        self,
        name: Optional[str] = None,
        *,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> None: ...

    def connect_keyspace(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> None: ...

    def create_bucket(
        self,
        name: Optional[str] = None,
        quota: Optional[int] = None,
        replicas: Optional[int] = None,
        bucket_type: Optional[Any] = None,
        storage_backend: Optional[Any] = None,
        bucket_data: Optional[BucketData] = None,
    ) -> None: ...

    def bucket_create(
        self,
        name: str,
        quota: int,
        replicas: int,
        bucket_type: BucketType,
        storage_backend: StorageBackend,
    ) -> None: ...

    def drop_bucket(self, name: Optional[str] = None) -> None: ...

    def create_scope(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
    ) -> None: ...

    def create_collection(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> None: ...

    def collection_exists(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
    ) -> bool: ...

    def create_primary_index(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        replica_count: Optional[int] = None,
    ) -> None: ...

    def create_secondary_index(
        self,
        index_name: str,
        index_keys: List[str],
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        replica_count: Optional[int] = None,
    ) -> None: ...

    def create_search_index(self, config: Mapping[str, Any]) -> None: ...

    def default_roles(self) -> Set[Role]: ...

    def construct_roles(self, roles: List[RoleData]) -> Set[Role]: ...

    def create_user(
        self,
        user_name: str,
        password: Optional[str],
        full_name: Optional[str],
        groups: Optional[List[str]],
        roles: Optional[List[RoleData]],
    ) -> None: ...

    def create_group(
        self,
        group_name: str,
        description: Optional[str],
        roles: Optional[List[RoleData]],
    ) -> None: ...

    def get(self, doc_id: str) -> Optional[Dict[str, Any]]: ...

    def upsert(self, doc_id: str, content: Any) -> None: ...

    def query(self, query_string: str) -> List[Dict[str, Any]]: ...

    def get_string_list(self, node: Any) -> List[str]: ...

    def get_search_indexes(self, bucket: str, scope: str) -> List[SearchIndexData]: ...

    def get_indexes(self, bucket: str, collection: str) -> List[IndexData]: ...

    def get_buckets(self) -> List[TableData]: ...

    def parse_role(self, role: Mapping[str, Any]) -> RoleData: ...

    def get_users(self) -> List[UserData]: ...

    def get_groups(self) -> List[GroupData]: ...

    def create_buckets(self, buckets: List[TableData]) -> None: ...


def resolve(config: CouchbaseConfig) -> CouchbaseConnect:
    if config.is_capella():
        from couchbase_connect.cloud import Capella

        return Capella.get_instance()
    from couchbase_connect.server import Server

    return Server.get_instance()


def get_instance() -> CouchbaseConnect:
    from couchbase_connect.auto import AutoCouchbaseConnect

    return cast(CouchbaseConnect, cast(object, AutoCouchbaseConnect.get_instance()))


@contextmanager
def open_connection(config: CouchbaseConfig) -> Iterator[CouchbaseConnect]:
    connection = resolve(config)
    connection.connect(config)
    try:
        yield connection
    finally:
        connection.disconnect()
