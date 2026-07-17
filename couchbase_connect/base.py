"""Shared Couchbase connection logic for Server and Capella backends."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Union
from uuid import uuid4

from couchbase.cluster import Cluster
from couchbase.collection import Collection
from couchbase.diagnostics import ServiceType
from couchbase.exceptions import (
    BucketNotFoundException,
    CollectionAlreadyExistsException,
    DocumentNotFoundException,
    ScopeAlreadyExistsException,
    SearchIndexNotFoundException,
    ServiceUnavailableException,
)
from couchbase.management.buckets import (
    BucketType,
    ConflictResolutionType,
    CreateBucketSettings,
    StorageBackend,
)
from couchbase.management.options import (
    CreatePrimaryQueryIndexOptions,
    CreateQueryIndexOptions,
    WatchQueryIndexOptions,
)
from couchbase.management.search import SearchIndex
from couchbase.management.users import Group, Role, User
from couchbase.n1ql import QueryScanConsistency
from couchbase.options import GetOptions, QueryOptions, UpsertOptions, WaitUntilReadyOptions
from couchbase.scope import Scope
from restfull.basic_auth import BasicAuth
from restfull.restapi import RestAPI

from couchbase_connect import cluster_create
from couchbase_connect.config import (
    CouchbaseConfig,
    convert_bucket_type,
    convert_storage_backend,
)
from couchbase_connect.exceptions import NotConnectedError
from couchbase_connect.models import (
    BucketData,
    CollectionData,
    GroupData,
    IndexData,
    RoleData,
    ScopeData,
    SearchIndexData,
    TableData,
    UserData,
)
from couchbase_connect.retry import linear_retry, with_index_creation_retry
from couchbase_connect.stream import CouchbaseStream

logger = logging.getLogger(__name__)


class AbstractCouchbaseConnect(ABC):

    def __init__(self) -> None:
        self.cluster: Optional[Cluster] = None
        self.bucket: Any = None
        self.scope: Optional[Scope] = None
        self.collection: Optional[Collection] = None
        self.properties: Dict[str, str] = {}
        self.connect_target: str = CouchbaseConfig.DEFAULT_HOSTNAME
        self.username: str = CouchbaseConfig.DEFAULT_USER
        self.password: str = CouchbaseConfig.DEFAULT_PASSWORD
        self.bucket_replicas: int = 1
        self.bucket_type: BucketType = BucketType.COUCHBASE
        self.bucket_storage: StorageBackend = StorageBackend.COUCHSTORE
        self.bucket_name: Optional[str] = None
        self.scope_name: Optional[str] = "_default"
        self.collection_name: Optional[str] = "_default"
        self.use_ssl: bool = True
        self.admin_port: int = 18091
        self.ttl_seconds: int = 0
        self.max_parallelism: int = 0
        self.kv_endpoints: int = 8
        self.kv_timeout: int = 5
        self.connect_timeout: int = 15
        self.query_timeout: int = 75
        self.cluster_info: Dict[str, Any] = {}
        self.cluster_version: str = ""
        self.major_revision: int = 0
        self.minor_revision: int = 0
        self.patch_revision: int = 0
        self.build_number: int = 0
        self.cluster_edition: str = ""
        self.enable_debug: bool = False
        self.host_map: List[Dict[str, Any]] = []

    def apply_config(self, config: CouchbaseConfig) -> None:
        self.connect_target = config.hostname
        self.username = config.username
        self.password = config.password
        self.enable_debug = config.enable_debug
        self.use_ssl = config.ssl_mode
        self.ttl_seconds = config.ttl_seconds
        self.bucket_name = config.bucket_name
        self.scope_name = config.scope_name or "_default"
        self.collection_name = config.collection_name or "_default"
        self.bucket_replicas = config.bucket_replicas
        self.bucket_type = config.bucket_type
        self.bucket_storage = config.bucket_storage
        self.max_parallelism = config.max_parallelism
        self.kv_endpoints = config.kv_endpoints
        self.kv_timeout = config.kv_timeout
        self.connect_timeout = config.connect_timeout
        self.query_timeout = config.query_timeout
        self.properties = dict(config.properties)
        if self.enable_debug:
            logging.getLogger("couchbase_connect").setLevel(logging.DEBUG)

    def finish_connect(self, config: CouchbaseConfig) -> None:
        if config.basic or self.cluster is None:
            return
        try:
            self.cluster.wait_until_ready(timedelta(seconds=15))
        except Exception as exc:  # noqa: BLE001
            logger.debug("wait_until_ready skipped/failed: %s", exc)
        if self.bucket_name:
            try:
                self.bucket = self.cluster.bucket(self.bucket_name)
            except BucketNotFoundException:
                pass
        self.load_cluster_info()

    @staticmethod
    def log_error(error: Exception, connect_string: str) -> None:
        logger.error("Connection string: %s", connect_string)
        logger.error("%s", error, exc_info=True)

    def load_cluster_info(self) -> None:
        auth = BasicAuth(self.username, self.password)
        api = RestAPI(
            auth,
            hostname=self.connect_target,
            use_ssl=bool(self.use_ssl),
            port=self.admin_port,
            verify=False,
        )
        payload = api.get("/pools/default").validate().json()
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected /pools/default response")
        self.cluster_info = payload
        nodes = payload.get("nodes") or []
        if not nodes:
            return
        cluster_full_version = str(nodes[0].get("version", "0.0.0-0-unknown"))
        parts = cluster_full_version.split("-")
        self.cluster_version = parts[0]
        self.build_number = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        self.cluster_edition = parts[2] if len(parts) > 2 else ""
        rev = self.cluster_version.split(".")
        self.major_revision = int(rev[0]) if len(rev) > 0 and rev[0].isdigit() else 0
        self.minor_revision = int(rev[1]) if len(rev) > 1 and rev[1].isdigit() else 0
        self.patch_revision = int(rev[2]) if len(rev) > 2 and rev[2].isdigit() else 0

        self.host_map = []
        for node in nodes:
            host_entry = str(node.get("hostname", ""))
            node_hostname = host_entry.split(":", 1)[0]
            self.host_map.append(
                {"hostname": node_hostname, "services": node.get("services") or []}
            )

        logger.debug(
            "Connected to Couchbase Server version %s with %s member(s)",
            self.cluster_version,
            len(self.host_map),
        )
        if len(self.host_map) == 1:
            self.bucket_replicas = 0
            logger.debug(
                "Single node cluster: setting bucket replicas to %s", self.bucket_replicas
            )

    def get_mem_quota(self) -> int:
        try:
            ram = (self.cluster_info.get("storageTotals") or {}).get("ram") or {}
            used = int(ram.get("quotaUsedPerNode", 0)) // 1048576
            total = int(ram.get("quotaTotalPerNode", 0)) // 1048576
            return max(total - used, 0)
        except (TypeError, ValueError):
            return 128

    def _admin_rest(self) -> RestAPI:
        return RestAPI(
            BasicAuth(self.username, self.password),
            hostname=self.connect_target,
            use_ssl=bool(self.use_ssl),
            port=self.admin_port,
            verify=False,
        )

    @abstractmethod
    def create_bucket_impl(self, bucket_settings: CreateBucketSettings) -> None: ...

    @abstractmethod
    def drop_bucket_impl(self, name: str) -> None: ...

    @abstractmethod
    def create_cluster_impl(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]],
    ) -> bool: ...

    @abstractmethod
    def destroy_cluster_impl(self) -> None: ...

    @abstractmethod
    def stream_hostname(self) -> str: ...

    @abstractmethod
    def supports_rbac_rest(self) -> bool: ...

    def create_cluster(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]] = None,
    ) -> bool:
        self.apply_config(config)
        return self.create_cluster_impl(config, options)

    def cluster_exists(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]] = None,
    ) -> bool:
        _ = options
        self.apply_config(config)
        return self.cluster is not None

    def destroy_cluster(self) -> None:
        self.destroy_cluster_impl()

    def stream(
        self,
        bucket_name: str,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> CouchbaseStream:
        if scope_name is None and collection_name is None:
            return CouchbaseStream(
                self.stream_hostname(),
                self.username,
                self.password,
                bucket_name,
                bool(self.use_ssl),
            )
        return CouchbaseStream(
            self.stream_hostname(),
            self.username,
            self.password,
            bucket_name,
            bool(self.use_ssl),
            scope_name or "_default",
            collection_name or "_default",
        )

    def admin_user_value(self) -> str:
        return self.username

    def admin_password_value(self) -> str:
        return self.password

    def get_bucket_name(self) -> Optional[str]:
        return self.bucket_name

    def get_scope_name(self) -> Optional[str]:
        return self.scope_name

    def get_collection_name(self) -> Optional[str]:
        return self.collection_name

    def get_cluster(self) -> Optional[Cluster]:
        return self.cluster

    def get_bucket(self) -> Any:
        return self.bucket

    def get_scope(self) -> Optional[Scope]:
        return self.scope

    def get_collection(self) -> Optional[Collection]:
        return self.collection

    def get_keyspace(self) -> str:
        return f"{self.bucket_name}.{self.scope_name}.{self.collection_name}"

    def get_index_node_count(self) -> int:
        count = 0
        for entry in self.host_map:
            services = entry.get("services") or []
            if "index" in services:
                count += 1
        return count

    def list_buckets(self) -> List[str]:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        return list(self._all_bucket_settings().keys())

    def _all_bucket_settings(self) -> Dict[str, Any]:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        buckets = self.cluster.buckets().get_all_buckets()
        if isinstance(buckets, dict):
            return buckets
        result: Dict[str, Any] = {}
        for item in buckets:
            name = getattr(item, "name", None)
            if name:
                result[str(name)] = item
        return result

    def is_bucket(self, bucket: Optional[str] = None) -> bool:
        name = bucket if bucket is not None else self.bucket_name
        if not name:
            return False
        return name in self.list_buckets()

    def bucket_exists(self, bucket_name: str) -> bool:
        return self.is_bucket(bucket_name)

    def cluster_wait(self) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        options = WaitUntilReadyOptions(
            service_types=[ServiceType.KeyValue, ServiceType.Query, ServiceType.View]
        )
        self.cluster.wait_until_ready(timedelta(seconds=30), options)
        self.wait_for_cluster_operations_ready()

    def wait_for_cluster_operations_ready(self) -> None:
        endpoint = self.cluster_rest_endpoint()
        if not endpoint.host or not self.username or not self.password:
            return
        cluster_create.wait_for_query_ready(endpoint, self.username, self.password)
        cluster_create.wait_for_rebalance_complete(endpoint, self.username, self.password)

    def cluster_rest_endpoint(self) -> cluster_create.ClusterRestEndpoint:
        return cluster_create.ClusterRestEndpoint.for_server(
            self.connect_target, bool(self.use_ssl)
        )

    def cluster_ping(self) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        logger.debug("cluster_ping")
        result = self.cluster.ping()
        endpoints = getattr(result, "endpoints", None) or {}
        for service, reports in endpoints.items():
            for report in reports:
                logger.debug("ping: %s: %s", service, report)

    def connect_bucket(self, name: Optional[str] = None) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        if name is not None:
            self.bucket_name = name
        if not self.bucket_name:
            raise ValueError("Bucket name is not configured")
        self.bucket = self.cluster.bucket(self.bucket_name)

    def connect_scope(self, name: Optional[str] = None) -> None:
        if self.bucket is None:
            raise NotConnectedError("Bucket is not connected")
        if name is not None:
            self.scope_name = name
        self.scope = self.bucket.scope(self.scope_name or "_default")

    def connect_collection(
        self,
        name: Optional[str] = None,
        collection_name: Optional[str] = None,
        *,
        scope_name: Optional[str] = None,
    ) -> None:
        if self.bucket is None:
            raise NotConnectedError("Bucket is not connected")
        if scope_name is not None and collection_name is not None:
            self.scope_name = scope_name
            self.collection_name = collection_name
            self.collection = self.bucket.scope(scope_name).collection(collection_name)
            return
        if name is not None and collection_name is not None:
            self.scope_name = name
            self.collection_name = collection_name
            self.collection = self.bucket.scope(name).collection(collection_name)
            return
        if name is not None:
            self.collection_name = name
        if self.scope is None:
            self.connect_scope()
        assert self.scope is not None
        self.collection = self.scope.collection(self.collection_name or "_default")

    def connect_keyspace(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        self.connect_bucket(bucket_name if bucket_name is not None else self.bucket_name)
        self.connect_scope(scope_name if scope_name is not None else self.scope_name)
        self.connect_collection(
            collection_name if collection_name is not None else self.collection_name
        )

    def create_bucket(
        self,
        name: Optional[str] = None,
        quota: Optional[int] = None,
        replicas: Optional[int] = None,
        bucket_type: Optional[Union[str, BucketType]] = None,
        storage_backend: Optional[Union[str, StorageBackend]] = None,
        bucket_data: Optional[BucketData] = None,
    ) -> None:
        if bucket_data is not None:
            self.bucket_create(
                bucket_data.name if bucket_data.name else "default",
                bucket_data.quota if bucket_data.quota else 128,
                bucket_data.replicas if bucket_data.replicas is not None else 1,
                convert_bucket_type(bucket_data.type),
                convert_storage_backend(bucket_data.storage),
            )
            return

        resolved_name = name or self.bucket_name
        if not resolved_name:
            raise ValueError("Bucket name is required")
        resolved_quota = self.get_mem_quota() if quota is None else quota
        resolved_replicas = self.bucket_replicas if replicas is None else replicas
        resolved_type = (
            self.bucket_type if bucket_type is None else convert_bucket_type(bucket_type)
        )
        resolved_storage = (
            self.bucket_storage
            if storage_backend is None
            else convert_storage_backend(storage_backend)
        )
        self.bucket_create(
            resolved_name,
            resolved_quota,
            resolved_replicas,
            resolved_type,
            resolved_storage,
        )

    def bucket_create(
        self,
        name: str,
        quota: int,
        replicas: int,
        bucket_type: BucketType,
        storage_backend: StorageBackend,
    ) -> None:
        if self.is_bucket(name):
            return
        if quota == 0:
            quota = 128
        settings = CreateBucketSettings(
            name=name,
            ram_quota_mb=quota,
            num_replicas=replicas,
            bucket_type=bucket_type,
            storage_backend=storage_backend,
            flush_enabled=False,
            replica_index=True,
            conflict_resolution_type=ConflictResolutionType.SEQUENCE_NUMBER,
        )
        self.create_bucket_impl(settings)

    def drop_bucket(self, name: Optional[str] = None) -> None:
        resolved = name or self.bucket_name
        if not resolved:
            raise ValueError("Bucket name is required")
        self.drop_bucket_impl(resolved)

    def create_scope(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
    ) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        b_name = bucket_name or self.bucket_name
        s_name = scope_name or self.scope_name or "_default"
        if s_name == "_default":
            return
        if not b_name:
            raise ValueError("Bucket name is required")
        self.bucket = self.cluster.bucket(b_name)
        try:
            self.bucket.collections().create_scope(s_name)
        except ScopeAlreadyExistsException:
            logger.debug("Scope %s already exists in cluster", s_name)

    def scope_exists(self, bucket_name: str, scope_name: str) -> bool:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        if not self.bucket_exists(bucket_name):
            return False
        bucket = self.cluster.bucket(bucket_name)
        return any(
            scope_spec.name == scope_name
            for scope_spec in bucket.collections().get_all_scopes()
        )

    def create_collection(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        b_name = bucket_name or self.bucket_name
        s_name = scope_name or self.scope_name or "_default"
        c_name = collection_name or self.collection_name or "_default"
        if c_name == "_default":
            return
        if not b_name:
            raise ValueError("Bucket name is required")
        self.bucket = self.cluster.bucket(b_name)
        try:
            self.bucket.collections().create_collection(s_name, c_name)
        except CollectionAlreadyExistsException:
            logger.debug("Collection %s already exists in cluster", c_name)

    def collection_exists(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
    ) -> bool:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        if not self.bucket_exists(bucket_name):
            return False
        bucket = self.cluster.bucket(bucket_name)
        for scope_spec in bucket.collections().get_all_scopes():
            if scope_spec.name != scope_name:
                continue
            return any(coll.name == collection_name for coll in scope_spec.collections)
        return False

    def ensure_collection(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
    ) -> Collection:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        self.create_bucket(bucket_name, quota=128)
        self.create_scope(bucket_name, scope_name)
        self.create_collection(bucket_name, scope_name, collection_name)
        self.connect_keyspace(bucket_name, scope_name, collection_name)
        assert self.collection is not None
        return self.collection

    def collection_is_empty(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
    ) -> bool:
        if not self.collection_exists(bucket_name, scope_name, collection_name):
            return True
        self.create_primary_index(bucket_name, scope_name, collection_name)
        keyspace = ".".join(
            f"`{part.replace('`', '``')}`"
            for part in (bucket_name, scope_name, collection_name)
        )
        return not self.query(f"SELECT RAW 1 FROM {keyspace} LIMIT 1")

    def populate_collection(
        self,
        json_lines_file: Union[str, Path],
        bucket_name: str,
        scope_name: str,
        collection_name: str,
    ) -> int:
        collection = self.ensure_collection(
            bucket_name, scope_name, collection_name
        )
        imported = 0
        with Path(json_lines_file).open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    document = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON on line {line_number} of {json_lines_file}"
                    ) from exc
                collection.upsert(str(uuid4()), document)
                imported += 1
        return imported

    def create_primary_index(
        self,
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        replica_count: Optional[int] = None,
    ) -> None:
        self._create_primary_index_internal(
            bucket_name or self.bucket_name or "",
            scope_name or self.scope_name or "_default",
            collection_name or self.collection_name or "_default",
            self.bucket_replicas if replica_count is None else replica_count,
        )

    @with_index_creation_retry()
    def _create_primary_index_internal(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
        replica_count: int,
    ) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        collection = (
            self.cluster.bucket(bucket_name).scope(scope_name).collection(collection_name)
        )
        query_index_mgr = collection.query_indexes()
        options = CreatePrimaryQueryIndexOptions(
            deferred=False,
            num_replicas=replica_count,
            ignore_if_exists=True,
        )
        logger.debug(
            "Creating Primary Index: Collection: %s replicas: %s",
            collection_name,
            replica_count,
        )
        query_index_mgr.create_primary_index(options)
        query_index_mgr.watch_indexes(
            ["#primary"],
            WatchQueryIndexOptions(timeout=timedelta(seconds=30)),
        )

    def create_secondary_index(
        self,
        index_name: str,
        index_keys: List[str],
        bucket_name: Optional[str] = None,
        scope_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        replica_count: Optional[int] = None,
    ) -> None:
        self._create_secondary_index_internal(
            bucket_name or self.bucket_name or "",
            scope_name or self.scope_name or "_default",
            collection_name or self.collection_name or "_default",
            index_name,
            index_keys,
            self.bucket_replicas if replica_count is None else replica_count,
        )

    @with_index_creation_retry()
    def _create_secondary_index_internal(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
        index_name: str,
        index_keys: List[str],
        replica_count: int,
    ) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        collection = (
            self.cluster.bucket(bucket_name).scope(scope_name).collection(collection_name)
        )
        query_index_mgr = collection.query_indexes()
        options = CreateQueryIndexOptions(
            deferred=False,
            num_replicas=replica_count,
            ignore_if_exists=True,
        )
        logger.debug(
            "Creating GSI: Collection: %s Name: %s Fields: %s replicas: %s",
            collection_name,
            index_name,
            index_keys,
            replica_count,
        )
        query_index_mgr.create_index(index_name, index_keys, options)
        query_index_mgr.watch_indexes(
            [index_name],
            WatchQueryIndexOptions(timeout=timedelta(seconds=30)),
        )

    @linear_retry()
    def _create_primary_index_bucketed(
        self,
        bucket_name: str,
        scope_name: str,
        collection_name: str,
        replica_count: int,
    ) -> None:
        self.create_primary_index(
            bucket_name, scope_name, collection_name, replica_count
        )

    @linear_retry()
    def _create_secondary_index_bucketed(
        self,
        index_name: str,
        index_keys: List[str],
        bucket_name: str,
        scope_name: str,
        collection_name: str,
        replica_count: int,
    ) -> None:
        self.create_secondary_index(
            index_name,
            index_keys,
            bucket_name=bucket_name,
            scope_name=scope_name,
            collection_name=collection_name,
            replica_count=replica_count,
        )

    def create_search_index(self, config: Mapping[str, Any]) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        search = self.cluster.search_indexes()
        name = str(config.get("name", ""))
        try:
            search.get_index(name)
        except SearchIndexNotFoundException:
            index = SearchIndex.from_json(dict(config))
            search.upsert_index(index)
        except ServiceUnavailableException:
            logger.debug("Search service is not configured in the cluster")

    def default_roles(self) -> Set[Role]:
        return {
            Role("data_reader", "*"),
            Role("query_select", "*"),
            Role("data_writer", "*"),
            Role("query_insert", "*"),
            Role("query_delete", "*"),
            Role("query_manage_index", "*"),
        }

    def construct_roles(self, roles: Optional[List[RoleData]]) -> Set[Role]:
        if not roles:
            return self.default_roles()
        role_list: Set[Role] = set()
        for role_data in roles:
            if role_data.scope_name != "*" or role_data.collection_name != "*":
                role = Role(
                    role_data.role,
                    role_data.bucket_name,
                    role_data.scope_name,
                    role_data.collection_name,
                )
            elif role_data.bucket_name != "*":
                role = Role(role_data.role, role_data.bucket_name)
            else:
                role = Role(role_data.role)
            role_list.add(role)
        return role_list

    def create_user(
        self,
        user_name: str,
        password: Optional[str],
        full_name: Optional[str],
        groups: Optional[List[str]],
        roles: Optional[List[RoleData]],
    ) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        user = User(username=user_name)
        if groups:
            user.groups = set(groups)
        user.roles = self.construct_roles(roles)
        user.password = password if password else self.password
        if full_name:
            user.display_name = full_name
        logger.debug("Creating user %s", user_name)
        self.cluster.users().upsert_user(user)

    def create_group(
        self,
        group_name: str,
        description: Optional[str],
        roles: Optional[List[RoleData]],
    ) -> None:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        group = Group(
            name=group_name,
            description=description or "",
            roles=self.construct_roles(roles),
        )
        logger.debug("Creating group %s", group_name)
        self.cluster.users().upsert_group(group)

    def get(self, doc_id: str) -> Optional[Dict[str, Any]]:
        if self.collection is None:
            raise NotConnectedError("Collection is not connected")
        try:
            result = self.collection.get(doc_id, GetOptions())
            content = result.content_as[dict]
            return content
        except DocumentNotFoundException:
            return None

    def upsert(self, doc_id: str, content: Any) -> None:
        if self.collection is None:
            raise NotConnectedError("Collection is not connected")
        try:
            options = UpsertOptions(timeout=timedelta(seconds=5))
            if self.ttl_seconds:
                options = UpsertOptions(
                    expiry=timedelta(seconds=self.ttl_seconds),
                    timeout=timedelta(seconds=5),
                )
            self.collection.upsert(doc_id, content, options)
        except Exception as exc:  # noqa: BLE001
            logger.error("%s", exc, exc_info=True)
            raise RuntimeError(str(exc)) from exc

    def query(self, query_string: str) -> List[Dict[str, Any]]:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        try:
            options = QueryOptions(
                scan_consistency=QueryScanConsistency.REQUEST_PLUS,
                max_parallelism=self.max_parallelism or None,
            )
            result = self.cluster.query(query_string, options)
            return [row for row in result.rows()]
        except Exception as exc:  # noqa: BLE001
            logger.error("%s", exc, exc_info=True)
            raise RuntimeError(str(exc)) from exc

    def get_string_list(self, node: Any) -> List[str]:
        if node is None:
            return []
        if isinstance(node, list):
            return [str(item) for item in node]
        return [str(node)]

    def get_search_indexes(self, bucket: str, scope: str) -> List[SearchIndexData]:
        result: List[SearchIndexData] = []
        if self.cluster is None:
            return result
        try:
            search = self.cluster.search_indexes()
            for index in search.get_all_indexes():
                source_name = getattr(index, "source_name", None) or getattr(
                    index, "sourceName", None
                )
                if source_name != bucket:
                    continue
                parts = str(index.name).split(".")
                if len(parts) < 3:
                    continue
                bucket_name, scope_name, index_name = parts[0], parts[1], parts[2]
                if scope_name != scope:
                    continue
                raw = index.as_dict() if hasattr(index, "as_dict") else {}
                if isinstance(raw, str):
                    import json

                    raw = json.loads(raw)
                result.append(
                    SearchIndexData(
                        name=index_name,
                        bucket=bucket_name,
                        scope=scope_name,
                        config=dict(raw) if isinstance(raw, dict) else {},
                    )
                )
        except ServiceUnavailableException:
            logger.debug("Search service is not configured in the cluster")
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_search_indexes failed: %s", exc)
        return result

    def get_indexes(self, bucket: str, collection: str) -> List[IndexData]:
        rows = self.query("SELECT * FROM system:indexes;")
        result: List[IndexData] = []
        for row in rows:
            index = row.get("indexes") if isinstance(row, dict) and "indexes" in row else row
            if not isinstance(index, dict):
                continue
            keyspace_id = str(index.get("keyspace_id", ""))
            if collection == "_default":
                if keyspace_id != bucket:
                    continue
            elif keyspace_id != collection:
                continue
            if index.get("using") and index.get("using") != "gsi":
                continue
            replicas = -1
            metadata = index.get("metadata") or {}
            if isinstance(metadata, dict) and "num_replica" in metadata:
                replicas = int(metadata["num_replica"])
            if index.get("is_primary"):
                result.append(
                    IndexData(
                        table=keyspace_id,
                        name=str(index.get("name", "")),
                        num_replicas=replicas,
                        is_primary=True,
                    )
                )
            else:
                result.append(
                    IndexData(
                        index_keys=self.get_string_list(index.get("index_key")),
                        table=keyspace_id,
                        name=str(index.get("name", "")),
                        num_replicas=replicas,
                        condition=str(index.get("condition") or ""),
                    )
                )
        return result

    def get_buckets(self) -> List[TableData]:
        if self.cluster is None:
            raise NotConnectedError("Cluster is not connected")
        result: List[TableData] = []
        for name, bucket_settings in self._all_bucket_settings().items():
            bucket = self.cluster.bucket(name)
            for scope_spec in bucket.collections().get_all_scopes():
                s_name = scope_spec.name
                if s_name == "_system":
                    continue
                for coll in scope_spec.collections:
                    c_name = coll.name
                    max_expiry = getattr(bucket_settings, "max_expiry", None)
                    ttl = int(max_expiry.total_seconds()) if max_expiry else 0
                    coll_expiry = getattr(coll, "max_expiry", None)
                    coll_ttl = int(coll_expiry.total_seconds()) if coll_expiry else 0
                    history = getattr(coll, "history", False) or False
                    b = BucketData(
                        name=name,
                        type=str(getattr(bucket_settings.bucket_type, "name", bucket_settings.bucket_type)).lower(),
                        quota=int(getattr(bucket_settings, "ram_quota_mb", 0) or 0),
                        replicas=int(getattr(bucket_settings, "num_replicas", 0) or 0),
                        eviction=str(getattr(bucket_settings, "eviction_policy", "")),
                        ttl=ttl,
                        storage=str(
                            getattr(
                                getattr(bucket_settings, "storage_backend", None),
                                "value",
                                getattr(bucket_settings, "storage_backend", ""),
                            )
                        ),
                        resolution=str(
                            getattr(
                                getattr(bucket_settings, "conflict_resolution_type", None),
                                "value",
                                "",
                            )
                        ),
                    )
                    result.append(
                        TableData(
                            name=name,
                            bucket=b,
                            scope=ScopeData(name=s_name),
                            collection=CollectionData(
                                name=c_name, ttl=coll_ttl, history=bool(history)
                            ),
                            indexes=self.get_indexes(name, c_name),
                            search_indexes=self.get_search_indexes(name, s_name),
                        )
                    )
        return result

    def parse_role(self, role: Mapping[str, Any]) -> RoleData:
        logger.debug("%s", dict(role))
        return RoleData(
            role=str(role.get("role", "")),
            bucket_name=str(role["bucket_name"]) if role.get("bucket_name") else "*",
            scope_name=str(role["scope_name"]) if role.get("scope_name") else "*",
            collection_name=(
                str(role["collection_name"]) if role.get("collection_name") else "*"
            ),
        )

    def get_users(self) -> List[UserData]:
        if not self.supports_rbac_rest() or self.major_revision < 5:
            return []
        result: List[UserData] = []
        try:
            payload = self._admin_rest().get("/settings/rbac/users").validate().json()
            if not isinstance(payload, list):
                return []
            for user in payload:
                if not isinstance(user, dict):
                    continue
                if user.get("domain") != "local":
                    continue
                u = UserData(
                    id=str(user.get("id", "")),
                    name=str(user.get("name", "")),
                    roles=[],
                    groups=[],
                )
                for role in user.get("roles") or []:
                    if isinstance(role, dict):
                        u.roles.append(self.parse_role(role))
                for group in user.get("groups") or []:
                    u.groups.append(str(group))
                result.append(u)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)) from exc
        return result

    def get_groups(self) -> List[GroupData]:
        if not self.supports_rbac_rest():
            return []
        if self.major_revision < 6 and self.minor_revision < 5:
            return []
        result: List[GroupData] = []
        try:
            payload = self._admin_rest().get("/settings/rbac/groups").validate().json()
            if not isinstance(payload, list):
                return []
            for group in payload:
                if not isinstance(group, dict):
                    continue
                ldap_ref = group.get("ldap_group_ref")
                if ldap_ref:
                    continue
                g = GroupData(
                    id=str(group.get("id", "")),
                    description=str(group.get("description", "")),
                    roles=[],
                )
                for role in group.get("roles") or []:
                    if isinstance(role, dict):
                        g.roles.append(self.parse_role(role))
                result.append(g)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(str(exc)) from exc
        return result

    def create_buckets(self, buckets: List[TableData]) -> None:
        for table in buckets:
            b_name = table.name
            scope = table.scope or ScopeData()
            collection = table.collection or CollectionData()
            s_name = scope.name
            c_name = collection.name

            logger.info("Creating bucket %s", b_name)
            if table.bucket is not None:
                self.create_bucket(bucket_data=table.bucket)
            else:
                self.create_bucket(name=b_name)

            if s_name != "_default":
                logger.info("Creating scope %s.%s", b_name, s_name)
                self.create_scope(b_name, s_name)

            if c_name != "_default":
                logger.info("Creating collection %s.%s.%s", b_name, s_name, c_name)
                self.create_collection(b_name, s_name, c_name)

            for index in table.indexes:
                replicas = (
                    index.num_replicas if index.num_replicas >= 0 else self.bucket_replicas
                )
                try:
                    if index.is_primary:
                        logger.info(
                            "Creating primary index on keyspace %s.%s.%s",
                            b_name,
                            s_name,
                            c_name,
                        )
                        self._create_primary_index_bucketed(
                            b_name, s_name, c_name, replicas
                        )
                    else:
                        logger.info(
                            "Creating secondary index %s on keyspace %s.%s.%s",
                            index.name,
                            b_name,
                            s_name,
                            c_name,
                        )
                        self._create_secondary_index_bucketed(
                            index.name,
                            index.index_keys,
                            b_name,
                            s_name,
                            c_name,
                            replicas,
                        )
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"Index creation failed: {exc}") from exc

            for search_index in table.search_indexes:
                logger.info("Creating search index %s", search_index.name)
                config = dict(search_index.config)
                config.pop("sourceUUID", None)
                config.pop("uuid", None)
                config["sourceType"] = "gocbcore"
                config["name"] = search_index.name
                self.create_search_index(config)
