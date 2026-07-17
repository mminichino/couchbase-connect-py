"""Couchbase connection configuration."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Union

from couchbase.management.buckets import BucketType, StorageBackend

from couchbase_connect.enums import KeyStoreType

SelfConfig = "CouchbaseConfig"


def convert_bucket_type(bucket_type: Union[str, BucketType]) -> BucketType:
    if isinstance(bucket_type, BucketType):
        return bucket_type
    value = bucket_type.lower()
    if value == "ephemeral":
        return BucketType.EPHEMERAL
    if value == "memcached":
        return BucketType.MEMCACHED
    return BucketType.COUCHBASE


def convert_storage_backend(
    storage_backend: Union[str, StorageBackend],
) -> StorageBackend:
    if isinstance(storage_backend, StorageBackend):
        return storage_backend
    if storage_backend.lower() == "magma":
        return StorageBackend.MAGMA
    return StorageBackend.COUCHSTORE


def convert_conflict_resolution_type(value: str) -> str:
    lowered = value.lower()
    if lowered == "custom":
        return "custom"
    if lowered in {"timestamp", "lww"}:
        return "lww"
    return "seqno"


class CouchbaseConfig:
    COUCHBASE_HOST = "couchbase.hostname"
    COUCHBASE_USER = "couchbase.username"
    COUCHBASE_PASSWORD = "couchbase.password"
    COUCHBASE_BUCKET = "couchbase.bucket"
    COUCHBASE_SCOPE = "couchbase.scope"
    COUCHBASE_COLLECTION = "couchbase.collection"
    COUCHBASE_CLIENT_CERTIFICATE = "couchbase.client.cert"
    COUCHBASE_ROOT_CERTIFICATE = "couchbase.ca.cert"
    COUCHBASE_KEYSTORE_TYPE = "couchbase.keystore.type"
    COUCHBASE_SSL_MODE = "couchbase.sslMode"
    COUCHBASE_REPLICA_NUM = "couchbase.replicaNum"
    COUCHBASE_TTL = "couchbase.ttlSeconds"
    COUCHBASE_MAX_PARALLELISM = "couchbase.maxParallelism"
    COUCHBASE_KV_ENDPOINTS = "couchbase.kvEndpoints"
    COUCHBASE_KV_TIMEOUT = "couchbase.kvTimeout"
    COUCHBASE_CONNECT_TIMEOUT = "couchbase.connectTimeout"
    COUCHBASE_QUERY_TIMEOUT = "couchbase.queryTimeout"
    COUCHBASE_BUCKET_TYPE = "couchbase.bucketType"
    COUCHBASE_STORAGE_TYPE = "couchbase.storageBackend"
    COUCHBASE_QUICK_CONNECT = "couchbase.quickConnect"
    COUCHBASE_SOFT_FAILURE = "couchbase.softFailure"
    COUCHBASE_DEBUG_MODE = "couchbase.debug"

    CAPELLA_ORGANIZATION_NAME = "capella.organization.name"
    CAPELLA_ORGANIZATION_ID = "capella.organization.id"
    CAPELLA_PROJECT_NAME = "capella.project.name"
    CAPELLA_PROJECT_ID = "capella.project.id"
    CAPELLA_DATABASE_NAME = "capella.database.name"
    CAPELLA_DATABASE_ID = "capella.database.id"
    CAPELLA_COLUMNAR_NAME = "capella.columnar.name"
    CAPELLA_COLUMNAR_ID = "capella.columnar.id"
    CAPELLA_TOKEN = "capella.token"
    CAPELLA_API_HOST = "capella.api.host"
    CAPELLA_USER_EMAIL = "capella.user.email"
    CAPELLA_USER_ID = "capella.user.id"

    COUCHBASE_SERVER_PREFIX = "couchbase.server"
    COUCHBASE_SERVER_EXT_API = "couchbase.server.extApi"
    CAPELLA_CLUSTER_ALLOW = "capella.cluster.allow"

    DEFAULT_USER = "Administrator"
    DEFAULT_PASSWORD = "password"
    DEFAULT_HOSTNAME = "127.0.0.1"
    DEFAULT_SSL_MODE = True

    def __init__(self) -> None:
        self._hostname = self.DEFAULT_HOSTNAME
        self._username = self.DEFAULT_USER
        self._password = self.DEFAULT_PASSWORD
        self._root_cert: Optional[str] = None
        self._client_cert: Optional[str] = None
        self._key_store_type = KeyStoreType.PKCS12
        self._ssl_mode = self.DEFAULT_SSL_MODE
        self._enable_debug = False
        self._bucket_name: Optional[str] = None
        self._scope_name: Optional[str] = None
        self._collection_name: Optional[str] = None
        self._bucket_replicas = 1
        self._max_parallelism = 0
        self._kv_endpoints = 8
        self._kv_timeout = 5
        self._connect_timeout = 15
        self._query_timeout = 75
        self._bucket_type = BucketType.COUCHBASE
        self._bucket_storage = StorageBackend.COUCHSTORE
        self._ttl_seconds = 0
        self._basic = False
        self._soft_failure = False
        self._properties: dict[str, str] = {}

    @staticmethod
    def server_quota_key(service: str) -> str:
        return f"couchbase.server.{service}.quota"

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str:
        return self._password

    @property
    def root_cert(self) -> Optional[str]:
        return self._root_cert

    @property
    def client_cert(self) -> Optional[str]:
        return self._client_cert

    @property
    def key_store_type(self) -> KeyStoreType:
        return self._key_store_type

    @property
    def ssl_mode(self) -> bool:
        return self._ssl_mode

    @property
    def enable_debug(self) -> bool:
        return self._enable_debug

    @property
    def bucket_name(self) -> Optional[str]:
        return self._bucket_name

    @property
    def scope_name(self) -> Optional[str]:
        return self._scope_name

    @property
    def collection_name(self) -> Optional[str]:
        return self._collection_name

    @property
    def bucket_replicas(self) -> int:
        return self._bucket_replicas

    @property
    def max_parallelism(self) -> int:
        return self._max_parallelism

    @property
    def kv_endpoints(self) -> int:
        return self._kv_endpoints

    @property
    def kv_timeout(self) -> int:
        return self._kv_timeout

    @property
    def connect_timeout(self) -> int:
        return self._connect_timeout

    @property
    def query_timeout(self) -> int:
        return self._query_timeout

    @property
    def bucket_type(self) -> BucketType:
        return self._bucket_type

    @property
    def bucket_storage(self) -> StorageBackend:
        return self._bucket_storage

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @property
    def basic(self) -> bool:
        return self._basic

    @property
    def soft_failure(self) -> bool:
        return self._soft_failure

    @property
    def properties(self) -> dict[str, str]:
        return self._properties

    def ttl(self, value: int) -> CouchbaseConfig:
        self._ttl_seconds = value
        return self

    def host(self, name: str) -> CouchbaseConfig:
        self._hostname = name
        return self

    def with_username(self, name: str) -> CouchbaseConfig:
        self._username = name
        return self

    def with_password(self, password: str) -> CouchbaseConfig:
        self._password = password
        return self

    def with_bucket_replicas(self, count: int) -> CouchbaseConfig:
        self._bucket_replicas = count
        return self

    def with_max_parallelism(self, count: int) -> CouchbaseConfig:
        self._max_parallelism = count
        return self

    def with_kv_endpoints(self, count: int) -> CouchbaseConfig:
        self._kv_endpoints = count
        return self

    def with_kv_timeout(self, timeout: int) -> CouchbaseConfig:
        self._kv_timeout = timeout
        return self

    def with_connect_timeout(self, timeout: int) -> CouchbaseConfig:
        self._connect_timeout = timeout
        return self

    def with_query_timeout(self, timeout: int) -> CouchbaseConfig:
        self._query_timeout = timeout
        return self

    def with_bucket_type(self, bucket_type: Union[str, BucketType]) -> CouchbaseConfig:
        self._bucket_type = convert_bucket_type(bucket_type)
        return self

    def with_bucket_storage(
        self, storage_backend: Union[str, StorageBackend]
    ) -> CouchbaseConfig:
        self._bucket_storage = convert_storage_backend(storage_backend)
        return self

    def root_cert_path(self, name: str) -> CouchbaseConfig:
        self._root_cert = name
        return self

    def client_key_store(self, name: str) -> CouchbaseConfig:
        self._client_cert = name
        return self

    def with_key_store_type(
        self, key_store_type: Union[KeyStoreType, str]
    ) -> CouchbaseConfig:
        self._key_store_type = (
            key_store_type
            if isinstance(key_store_type, KeyStoreType)
            else KeyStoreType(str(key_store_type).upper())
        )
        return self

    def connect(self, host: str, user: str, password: str) -> CouchbaseConfig:
        self._hostname = host
        self._username = user
        self._password = password
        return self

    def ssl(self, mode: bool) -> CouchbaseConfig:
        self._ssl_mode = mode
        return self

    def bucket(self, name: str) -> CouchbaseConfig:
        self._bucket_name = name
        return self

    def scope(self, scope: str) -> CouchbaseConfig:
        self._scope_name = scope
        return self

    def collection(self, name: str) -> CouchbaseConfig:
        self._collection_name = name
        return self

    def with_enable_debug(self, mode: bool) -> CouchbaseConfig:
        self._enable_debug = mode
        return self

    def quick_connect(self, mode: bool) -> CouchbaseConfig:
        self._basic = mode
        return self

    def with_soft_failure(self, mode: bool) -> CouchbaseConfig:
        self._soft_failure = mode
        return self

    def organization(self, name: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_ORGANIZATION_NAME, name)
        return self

    def organization_id(self, org_id: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_ORGANIZATION_ID, org_id)
        return self

    def project(self, name: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_PROJECT_NAME, name)
        return self

    def project_id(self, project_id: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_PROJECT_ID, project_id)
        return self

    def database(self, name: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_DATABASE_NAME, name)
        return self

    def database_id(self, database_id: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_DATABASE_ID, database_id)
        return self

    def columnar(self, name: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_COLUMNAR_NAME, name)
        return self

    def columnar_id(self, columnar_id: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_COLUMNAR_ID, columnar_id)
        return self

    def user_email(self, email: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_USER_EMAIL, email)
        return self

    def user_id(self, user_id: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_USER_ID, user_id)
        return self

    def token(self, token: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_TOKEN, token)
        return self

    def api_host(self, host: str) -> CouchbaseConfig:
        self._set_capella_property(self.CAPELLA_API_HOST, host)
        return self

    def from_mapping(self, properties: Mapping[str, Any]) -> CouchbaseConfig:
        props = {str(k): str(v) for k, v in properties.items() if v is not None}
        self._hostname = props.get(self.COUCHBASE_HOST, self.DEFAULT_HOSTNAME)
        self._username = props.get(self.COUCHBASE_USER, self.DEFAULT_USER)
        self._password = props.get(self.COUCHBASE_PASSWORD, self.DEFAULT_PASSWORD)
        self._client_cert = props.get(self.COUCHBASE_CLIENT_CERTIFICATE)
        self._root_cert = props.get(self.COUCHBASE_ROOT_CERTIFICATE)
        self._key_store_type = KeyStoreType(
            props.get(self.COUCHBASE_KEYSTORE_TYPE, "PKCS12").upper()
        )
        self._bucket_name = props.get(self.COUCHBASE_BUCKET, "default")
        self._scope_name = props.get(self.COUCHBASE_SCOPE, "_default")
        self._collection_name = props.get(self.COUCHBASE_COLLECTION, "_default")
        self._ssl_mode = props.get(self.COUCHBASE_SSL_MODE, "true").lower() == "true"
        self._bucket_replicas = int(props.get(self.COUCHBASE_REPLICA_NUM, "1"))
        self._max_parallelism = int(props.get(self.COUCHBASE_MAX_PARALLELISM, "0"))
        self._kv_endpoints = int(props.get(self.COUCHBASE_KV_ENDPOINTS, "8"))
        self._kv_timeout = int(props.get(self.COUCHBASE_KV_TIMEOUT, "5"))
        self._connect_timeout = int(props.get(self.COUCHBASE_CONNECT_TIMEOUT, "15"))
        self._query_timeout = int(props.get(self.COUCHBASE_QUERY_TIMEOUT, "75"))
        self._ttl_seconds = int(props.get(self.COUCHBASE_TTL, "0"))
        self._bucket_type = convert_bucket_type(
            props.get(self.COUCHBASE_BUCKET_TYPE, "couchbase")
        )
        self._bucket_storage = convert_storage_backend(
            props.get(self.COUCHBASE_STORAGE_TYPE, "couchstore")
        )
        self._basic = props.get(self.COUCHBASE_QUICK_CONNECT, "false").lower() == "true"
        self._soft_failure = (
            props.get(self.COUCHBASE_SOFT_FAILURE, "false").lower() == "true"
        )
        self._enable_debug = (
            props.get(self.COUCHBASE_DEBUG_MODE, "false").lower() == "true"
        )
        self._apply_capella_from_mapping(props)
        self._properties.update(props)
        return self

    def _set_capella_property(self, key: str, value: Optional[str]) -> None:
        if value is not None:
            self._properties[key] = value

    def _apply_capella_from_mapping(self, source: Mapping[str, str]) -> None:
        for key in (
            self.CAPELLA_ORGANIZATION_NAME,
            self.CAPELLA_ORGANIZATION_ID,
            self.CAPELLA_PROJECT_NAME,
            self.CAPELLA_PROJECT_ID,
            self.CAPELLA_DATABASE_NAME,
            self.CAPELLA_DATABASE_ID,
            self.CAPELLA_COLUMNAR_NAME,
            self.CAPELLA_COLUMNAR_ID,
            self.CAPELLA_TOKEN,
            self.CAPELLA_API_HOST,
            self.CAPELLA_USER_EMAIL,
            self.CAPELLA_USER_ID,
        ):
            if key in source:
                self._properties[key] = source[key]

    def is_capella(self) -> bool:
        token = self._properties.get(self.CAPELLA_TOKEN)
        return bool(token and token.strip())

    @staticmethod
    def is_capella_properties(properties: Mapping[str, str]) -> bool:
        token = properties.get(CouchbaseConfig.CAPELLA_TOKEN)
        return bool(token and token.strip())
