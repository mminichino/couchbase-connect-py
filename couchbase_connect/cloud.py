"""Capella connection backend."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from couchbase.management.buckets import CreateBucketSettings

from couchbase_connect import cluster_create
from couchbase_connect.base import AbstractCouchbaseConnect
from couchbase_connect.capella import (
    CapellaAPIError,
    CapellaBucket,
    CapellaCluster,
    CapellaConnectivity,
    CapellaNotFoundError,
    CapellaOrganization,
    CapellaProject,
    CouchbaseCapella,
    connect_cluster,
    disconnect_cluster,
)
from couchbase_connect.config import CouchbaseConfig

logger = logging.getLogger(__name__)


class Capella(AbstractCouchbaseConnect):

    _instance: Optional["Capella"] = None

    def __init__(self) -> None:
        super().__init__()
        self.capella_cluster: Optional[CapellaCluster] = None
        self.database_name: str = ""
        self.stream_host: str = ""

    @classmethod
    def get_instance(cls) -> "Capella":
        if cls._instance is None:
            cls._instance = cls()
        assert cls._instance is not None
        return cls._instance

    def connect(self, config: CouchbaseConfig) -> None:
        self.apply_config(config)
        self.use_ssl = True
        self.admin_port = 18091
        soft_failure = config.soft_failure

        self._resolve_database_name(config)
        self._validate_capella_config()

        try:
            if self.cluster is not None and self.capella_cluster is None:
                disconnect_cluster(self.cluster)
                self.cluster = None
            if self.cluster is not None:
                return

            logger.info("Connecting to Couchbase Capella database %s", self.database_name)

            api = CouchbaseCapella.from_properties(self.properties)
            organization = CapellaOrganization.get_instance(api)
            project = CapellaProject.get_instance(organization)
            self.capella_cluster = CapellaCluster.get_instance(project, self.database_name)

            credentials = self.capella_cluster.get_credentials()
            if credentials is not None:
                credentials.add_credentials(self.username, self.password)

            connect_string = self.capella_cluster.get_connect_string() or ""
            if not CapellaConnectivity().check_connectivity(
                connect_string, timeout=120.0
            ):
                raise RuntimeError(
                    f"Capella cluster is not reachable at {connect_string}"
                )

            cert = self.capella_cluster.get_certificate()
            certificate_pem = None
            if cert is not None:
                certificate_pem = cert.certificate_pem
                if not certificate_pem:
                    try:
                        certificate_pem = cert.get_cluster_certificate()
                    except CapellaAPIError as exc:
                        logger.debug("Unable to fetch Capella certificate: %s", exc)

            self.cluster = connect_cluster(
                connect_string,
                self.username,
                self.password,
                certificate_pem=certificate_pem,
                kv_endpoints=self.kv_endpoints,
                kv_timeout=self.kv_timeout,
                connect_timeout=self.connect_timeout,
                query_timeout=self.query_timeout,
            )
            self.connect_target = self.database_name
            self.stream_host = self._extract_host(connect_string)
            logger.debug("Capella cluster connected for database %s", self.database_name)
            self.finish_connect(config)
        except Exception as exc:  # noqa: BLE001
            connect_label = (
                self.capella_cluster.get_connect_string()
                if self.capella_cluster is not None
                else self.database_name
            )
            self.log_error(exc, connect_label or self.database_name)
            if not soft_failure:
                raise RuntimeError(str(exc)) from exc

    def _resolve_database_name(self, config: CouchbaseConfig) -> None:
        database_name = self.properties.get(CouchbaseConfig.CAPELLA_DATABASE_NAME)
        if not database_name or not database_name.strip():
            database_name = self.properties.get(CouchbaseConfig.CAPELLA_DATABASE_ID)
        if not database_name or not database_name.strip():
            database_name = self.connect_target
        self.database_name = database_name
        self.properties[CouchbaseConfig.CAPELLA_DATABASE_NAME] = self.database_name
        self.connect_target = self.database_name

    def _validate_capella_config(self) -> None:
        if not self._capella_token_set():
            raise ValueError(
                f"Capella connection requires {CouchbaseConfig.CAPELLA_TOKEN}"
            )
        if not self._capella_project_set():
            raise ValueError(
                "Capella connection requires "
                f"{CouchbaseConfig.CAPELLA_PROJECT_NAME} or "
                f"{CouchbaseConfig.CAPELLA_PROJECT_ID}"
            )
        if not self._capella_database_set():
            raise ValueError(
                "Capella connection requires "
                f"{CouchbaseConfig.CAPELLA_DATABASE_NAME} or "
                f"{CouchbaseConfig.CAPELLA_DATABASE_ID}"
            )
        if not self._capella_user_set():
            raise ValueError(
                "Capella connection requires "
                f"{CouchbaseConfig.CAPELLA_USER_EMAIL} or "
                f"{CouchbaseConfig.CAPELLA_USER_ID}"
            )

    def _capella_token_set(self) -> bool:
        return self.properties.get(CouchbaseConfig.CAPELLA_TOKEN) is not None

    def _capella_project_set(self) -> bool:
        return (
            self.properties.get(CouchbaseConfig.CAPELLA_PROJECT_ID) is not None
            or self.properties.get(CouchbaseConfig.CAPELLA_PROJECT_NAME) is not None
        )

    def _capella_database_set(self) -> bool:
        return (
            self.properties.get(CouchbaseConfig.CAPELLA_DATABASE_ID) is not None
            or self.properties.get(CouchbaseConfig.CAPELLA_DATABASE_NAME) is not None
        )

    def _capella_user_set(self) -> bool:
        return (
            self.properties.get(CouchbaseConfig.CAPELLA_USER_EMAIL) is not None
            or self.properties.get(CouchbaseConfig.CAPELLA_USER_ID) is not None
        )

    @staticmethod
    def _extract_host(connect_string: Optional[str]) -> str:
        if not connect_string or not connect_string.strip():
            return ""
        stripped = connect_string
        for prefix in ("couchbases://", "couchbase://"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :]
                break
        stripped = stripped.split(",", 1)[0]
        stripped = stripped.split("?", 1)[0]
        return stripped

    def disconnect(self) -> None:
        self.bucket = None
        self.scope = None
        self.collection = None
        if self.cluster is not None:
            disconnect_cluster(self.cluster)
        self.cluster = None
        self.capella_cluster = None
        self.cluster_info = {}

    def host_value(self) -> str:
        return self.database_name

    def get_mem_quota(self) -> int:
        return 128

    def load_cluster_info(self) -> None:
        self.major_revision = 7
        self.minor_revision = 0
        self.patch_revision = 0

    def list_buckets(self) -> List[str]:
        if self.capella_cluster is None:
            raise RuntimeError("Capella cluster is not connected")
        try:
            return [item.name for item in CapellaBucket.get_instance(self.capella_cluster).list() if item.name is not None]
        except CapellaAPIError as exc:
            raise RuntimeError("Failed to list Capella buckets") from exc

    def create_bucket_impl(self, bucket_settings: CreateBucketSettings) -> None:
        if self.capella_cluster is None:
            raise RuntimeError("Capella cluster is not connected")
        try:
            CapellaBucket.get_instance(self.capella_cluster).create_bucket(
                self._to_capella_bucket_settings(bucket_settings)
            )
        except CapellaAPIError as exc:
            logger.error("bucketCreate: Capella API error", exc_info=True)
            raise RuntimeError("bucketCreate: Capella API error") from exc

    @staticmethod
    def _to_capella_bucket_settings(settings: CreateBucketSettings) -> Dict[str, Any]:
        bucket_type = settings.get("bucket_type")
        type_name = getattr(bucket_type, "name", None)
        if type_name:
            type_str = str(type_name).lower()
        else:
            raw = str(getattr(bucket_type, "value", bucket_type or "couchbase")).lower()
            type_str = "couchbase" if raw == "membase" else raw

        storage = settings.get("storage_backend")
        storage_str = str(getattr(storage, "value", storage or "couchstore"))

        conflict = settings.get("conflict_resolution_type")
        conflict_str = str(getattr(conflict, "value", conflict or "seqno"))

        num_replicas: int | None = settings.get("num_replicas")
        return {
            "name": settings.get("name"),
            "type": type_str,
            "storageBackend": storage_str,
            "memoryAllocationInMb": int(settings.get("ram_quota_mb", 128) or 128),
            "replicas": 1 if num_replicas is None else int(num_replicas),
            "flush": bool(settings.get("flush_enabled", False)),
            "bucketConflictResolution": conflict_str,
        }

    def drop_bucket_impl(self, name: str) -> None:
        if self.capella_cluster is None:
            raise RuntimeError("Capella cluster is not connected")
        try:
            CapellaBucket.get_instance(self.capella_cluster, name).delete()
        except CapellaNotFoundError:
            logger.debug("Drop: Bucket %s does not exist", name)
        except CapellaAPIError as exc:
            logger.error("dropBucket: Capella API error", exc_info=True)
            raise RuntimeError("dropBucket: Capella API error") from exc

    def create_cluster_impl(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]],
    ) -> None:
        merged = cluster_create.merge_options(config, options)
        self.properties.update(merged)
        self._resolve_database_name(config)
        self._validate_capella_config()

        try:
            api = CouchbaseCapella.from_properties(merged)
            organization = CapellaOrganization.get_instance(api)
            project = CapellaProject.get_instance(organization)
            nodes = cluster_create.parse_capella_nodes(merged)
            cluster_config = cluster_create.build_capella_cluster_config(merged, nodes)
            self.capella_cluster = project.create_cluster(
                self.database_name, cluster_config
            )

            allowed_cidr = merged.get(
                CouchbaseConfig.CAPELLA_CLUSTER_ALLOW, "0.0.0.0/0"
            )
            allowed = self.capella_cluster.get_allowed_cidr()
            if allowed is not None:
                allowed.create_allowed_cidr(allowed_cidr)
            credentials = self.capella_cluster.get_credentials()
            if credentials is not None:
                credentials.create_credential(self.username, self.password, None)

            connect_string = self.capella_cluster.get_connect_string() or ""
            if not CapellaConnectivity().check_connectivity(
                connect_string, timeout=300.0
            ):
                raise RuntimeError("Capella cluster connectivity check failed")

            self.stream_host = self._extract_host(connect_string)
            self.connect_target = self.database_name
            endpoint = cluster_create.ClusterRestEndpoint.for_capella(self.stream_host)
            cluster_create.wait_for_cluster_services(
                endpoint, self.username, self.password
            )
            cluster_create.wait_for_query_ready(endpoint, self.username, self.password)
            cluster_create.wait_for_rebalance_complete(
                endpoint, self.username, self.password
            )
            logger.info("Capella cluster %s created", self.database_name)
        except CapellaAPIError as e:
            raise RuntimeError("Failed to create Capella cluster") from e

    def destroy_cluster_impl(self) -> None:
        if self.capella_cluster is None:
            return
        try:
            self.capella_cluster.delete()
            logger.info("Capella cluster %s destroyed", self.database_name)
        except CapellaAPIError as exc:
            raise RuntimeError("Failed to destroy Capella cluster") from exc
        finally:
            self.capella_cluster = None
            self.bucket = None
            if self.cluster is not None:
                disconnect_cluster(self.cluster)
                self.cluster = None
            self.stream_host = ""

    def stream_hostname(self) -> str:
        return self.stream_host

    def cluster_rest_endpoint(self) -> cluster_create.ClusterRestEndpoint:
        return cluster_create.ClusterRestEndpoint.for_capella(self.stream_host)

    def supports_rbac_rest(self) -> bool:
        return False
