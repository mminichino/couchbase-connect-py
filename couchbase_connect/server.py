"""Couchbase Server hostname-based connection."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Mapping, Optional, Any

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.exceptions import BucketAlreadyExistsException, BucketNotFoundException
from couchbase.management.buckets import CreateBucketSettings
from couchbase.options import ClusterOptions, ClusterTimeoutOptions, TLSVerifyMode

from couchbase_connect import cluster_create
from couchbase_connect.base import AbstractCouchbaseConnect
from couchbase_connect.config import CouchbaseConfig

logger = logging.getLogger(__name__)


class Server(AbstractCouchbaseConnect):

    _instance: Optional["Server"] = None

    @classmethod
    def get_instance(cls) -> "Server":
        if cls._instance is None:
            cls._instance = cls()
        assert cls._instance is not None
        return cls._instance

    def connect(self, config: CouchbaseConfig) -> None:
        self.apply_config(config)
        prefix = "couchbases://" if self.use_ssl else "couchbase://"
        self.admin_port = 18091 if self.use_ssl else 8091
        connect_string = f"{prefix}{self.connect_target}"
        soft_failure = config.soft_failure

        try:
            if self.cluster is not None:
                return

            timeout_opts = ClusterTimeoutOptions(
                kv_timeout=timedelta(seconds=self.kv_timeout),
                connect_timeout=timedelta(seconds=self.connect_timeout),
                query_timeout=timedelta(seconds=self.query_timeout),
            )

            auth_kwargs = {}
            if config.client_cert:
                logger.debug(
                    "client certificate configured (%s); using password authenticator",
                    config.client_cert,
                )
            authenticator = PasswordAuthenticator(self.username, self.password, **auth_kwargs)

            option_kwargs: dict[str, Any] = {
                "timeout_options": timeout_opts,
                "enable_tls": bool(self.use_ssl),
                "enable_mutation_tokens": False,
            }
            if config.root_cert:
                option_kwargs["trust_store_path"] = config.root_cert
                option_kwargs["tls_verify"] = TLSVerifyMode.PEER
            elif self.use_ssl:
                option_kwargs["tls_verify"] = TLSVerifyMode.NONE

            options = ClusterOptions(authenticator, **option_kwargs)
            logger.debug("connecting as user %s", self.username)
            try:
                self.cluster = Cluster.connect(connect_string, options)
            except Exception:
                self.cluster = Cluster(connect_string, options)

            logger.debug("%s cluster connected", self.connect_target)
            self.finish_connect(config)
        except Exception as exc:  # noqa: BLE001
            self.log_error(exc, connect_string)
            if not soft_failure:
                raise RuntimeError(str(exc)) from exc

    def disconnect(self) -> None:
        self.bucket = None
        self.scope = None
        self.collection = None
        if self.cluster is not None:
            try:
                self.cluster.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("disconnect: %s", exc)
        self.cluster = None
        self.cluster_info = {}

    def host_value(self) -> str:
        return self.connect_target

    def create_cluster(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]] = None,
    ) -> bool:
        created = super().create_cluster(config, options)
        if not created:
            print("Cluster already configured")
        return created

    def create_bucket_impl(self, bucket_settings: CreateBucketSettings) -> None:
        if self.cluster is None:
            raise RuntimeError("Cluster is not connected")
        try:
            self.cluster.buckets().create_bucket(bucket_settings)
        except BucketAlreadyExistsException:
            logger.debug(
                "bucketCreate: Bucket %s already exists",
                bucket_settings.get("name"),
            )

    def drop_bucket_impl(self, name: str) -> None:
        if self.cluster is None:
            raise RuntimeError("Cluster is not connected")
        try:
            self.cluster.buckets().drop_bucket(name)
        except BucketNotFoundException:
            logger.debug("Drop: Bucket %s does not exist", name)

    def create_cluster_impl(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]],
    ) -> bool:
        merged = cluster_create.merge_options(config, options)
        nodes = cluster_create.parse_server_nodes(merged)
        if not nodes:
            raise ValueError("At least one Couchbase Server node must be configured")

        admin_rest_port = 8091 if config.ssl_mode is False else 18091
        use_ssl = config.ssl_mode is not False
        use_ext_api = cluster_create.parse_use_ext_api(merged)
        node_hosts = []
        try:
            first_node = nodes[0]
            first_internal = cluster_create.parse_host_port(
                first_node.ip, admin_rest_port
            )
            endpoint = cluster_create.node_endpoint(first_node, use_ssl, use_ext_api)

            if cluster_create.is_cluster_initialized(
                endpoint, config.username, config.password
            ):
                logger.debug("Cluster already initialized on %s", endpoint.host)
                self.connect_target = endpoint.host
                return False

            # Management API must be reachable on every node before bootstrap.
            cluster_create.wait_for_nodes_api(nodes, use_ssl, use_ext_api)

            quotas = cluster_create.calculate_server_quotas(first_node, merged)
            logger.debug(
                "Creating single-node cluster via %s (ssl=%s, ext_api=%s) with quotas %s",
                endpoint.host,
                use_ssl,
                use_ext_api,
                quotas,
            )
            cluster_create.initialize_single_node_cluster(
                endpoint,
                config.username,
                config.password,
                first_node.services,
                quotas,
                cluster_hostname=first_internal.host,
            )
            node_hosts.append(cluster_create.cluster_init_hostname(first_internal.host))

            for node in nodes[1:]:
                node_internal = cluster_create.parse_host_port(node.ip, admin_rest_port)
                cluster_create.add_node_to_cluster(
                    endpoint,
                    config.username,
                    config.password,
                    node_internal.host,
                    node.services,
                )
                node_hosts.append(
                    cluster_create.cluster_init_hostname(node_internal.host)
                )

            if len(nodes) > 1:
                cluster_create.rebalance_cluster(
                    endpoint,
                    config.username,
                    config.password,
                    node_hosts,
                )

            cluster_create.wait_for_cluster(
                endpoint, config.username, config.password, 60
            )
            cluster_create.wait_for_rebalance_complete(
                endpoint, config.username, config.password
            )
            cluster_create.wait_for_cluster_services(
                endpoint, config.username, config.password
            )
            cluster_create.wait_for_query_ready(
                endpoint, config.username, config.password
            )
            cluster_create.apply_alternate_addresses(
                nodes,
                config.username,
                config.password,
                use_ssl,
                use_ext_api,
            )
            self.connect_target = endpoint.host
            return True
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Failed to create Couchbase Server cluster") from exc

    def cluster_exists(
        self,
        config: CouchbaseConfig,
        options: Optional[Mapping[str, str]] = None,
    ) -> bool:
        merged = cluster_create.merge_options(config, options)
        nodes = cluster_create.parse_server_nodes(merged)
        if not nodes:
            return False
        use_ssl = config.ssl_mode is not False
        use_ext_api = cluster_create.parse_use_ext_api(merged)
        endpoint = cluster_create.node_endpoint(nodes[0], use_ssl, use_ext_api)
        return cluster_create.is_cluster_initialized(
            endpoint, config.username, config.password
        )

    def destroy_cluster_impl(self) -> None:
        logger.debug("destroy_cluster is not supported for Couchbase Server")

    def stream_hostname(self) -> str:
        return self.connect_target

    def supports_rbac_rest(self) -> bool:
        return True
