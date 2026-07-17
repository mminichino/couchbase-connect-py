"""Cluster bootstrap helpers for Couchbase Server and Capella readiness waits."""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence

from restfull.basic_auth import BasicAuth
from restfull.no_auth import NoAuth
from restfull.restapi import RestAPI

from couchbase_connect.capella.cluster import ClusterConfig, ServiceGroupConfig
from couchbase_connect.capella.models import AvailabilityType
from couchbase_connect.config import CouchbaseConfig
from couchbase_connect.exceptions import ClusterCreateError
from couchbase_connect.models import CapellaNodeConfig, ClusterNodeConfig

logger = logging.getLogger(__name__)

DEFAULT_SERVER_SERVICES = ["data", "index", "query", "fts"]
DEFAULT_CAPELLA_SERVICES = ["data", "query", "index", "search"]
SERVER_NODE_PATTERN = re.compile(r"^couchbase\.server\.(\d+)\.(.+)$")
CAPELLA_NODE_PATTERN = re.compile(r"^capella\.cluster\.node\.(\d+)\.(.+)$")


@dataclass(frozen=True)
class HostPort:
    host: str
    port: int


@dataclass(frozen=True)
class ClusterRestEndpoint:
    host: str
    admin_port: int
    query_port: int
    use_ssl: bool

    @classmethod
    def for_server(cls, host: str, use_ssl: bool) -> "ClusterRestEndpoint":
        return cls(
            host=host,
            admin_port=18091 if use_ssl else 8091,
            query_port=18093 if use_ssl else 8093,
            use_ssl=use_ssl,
        )

    @classmethod
    def for_capella(cls, host: str) -> "ClusterRestEndpoint":
        return cls(host=host, admin_port=18091, query_port=18093, use_ssl=True)


def merge_options(
    config: CouchbaseConfig,
    options: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    merged: Dict[str, str] = dict(config.properties)
    if options:
        merged.update(options)
    merged.setdefault(CouchbaseConfig.COUCHBASE_USER, config.username)
    merged.setdefault(CouchbaseConfig.COUCHBASE_PASSWORD, config.password)
    if config.hostname:
        merged.setdefault(CouchbaseConfig.COUCHBASE_HOST, config.hostname)
    return merged


def parse_host_port(value: Optional[str], default_port: int) -> HostPort:
    if not value or not value.strip():
        return HostPort(CouchbaseConfig.DEFAULT_HOSTNAME, default_port)
    host_value = value.split("/", 1)[0]
    if ":" in host_value:
        host, port_text = host_value.split(":", 1)
        return HostPort(host, int(port_text))
    return HostPort(host_value, default_port)


def parse_use_ext_api(options: Mapping[str, str]) -> bool:
    value = options.get(CouchbaseConfig.COUCHBASE_SERVER_EXT_API)
    if value is None or not str(value).strip():
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def api_host_for_node(node: ClusterNodeConfig, use_ext_api: bool) -> str:
    if use_ext_api and node.alternate_address:
        return parse_host_port(node.alternate_address, 8091).host
    return parse_host_port(node.ip, 8091).host


def node_endpoint(
    node: ClusterNodeConfig,
    use_ssl: bool,
    use_ext_api: bool = False,
) -> ClusterRestEndpoint:
    return ClusterRestEndpoint.for_server(api_host_for_node(node, use_ext_api), use_ssl)


def parse_server_nodes(options: Mapping[str, str]) -> List[ClusterNodeConfig]:
    nodes: Dict[int, ClusterNodeConfig] = {}
    for key, value in options.items():
        match = SERVER_NODE_PATTERN.match(key)
        if not match:
            continue
        index = int(match.group(1))
        field = match.group(2)
        node = nodes.setdefault(index, ClusterNodeConfig())
        if field == "ip":
            node.ip = value
        elif field == "ram":
            node.ram_gib = int(value)
        elif field == "services":
            node.services = _parse_services(value, DEFAULT_SERVER_SERVICES)
        elif field in {"alternateAddress", "alternate", "external"}:
            node.alternate_address = value.strip() or None
        elif field == "alternatePorts":
            node.alternate_ports.update(parse_alternate_ports(value))
        elif field.startswith("alternatePort."):
            service = field.split(".", 1)[1].strip()
            if service and value.strip():
                node.alternate_ports[_to_rest_service(service)] = int(value.strip())
    if not nodes:
        nodes[0] = ClusterNodeConfig(
            ip=options.get(CouchbaseConfig.COUCHBASE_HOST, CouchbaseConfig.DEFAULT_HOSTNAME),
            services=list(DEFAULT_SERVER_SERVICES),
        )
    return [nodes[key] for key in sorted(nodes)]


def parse_capella_nodes(options: Mapping[str, str]) -> List[CapellaNodeConfig]:
    nodes: Dict[int, CapellaNodeConfig] = {}
    for key, value in options.items():
        match = CAPELLA_NODE_PATTERN.match(key)
        if not match:
            continue
        index = int(match.group(1))
        field = match.group(2)
        node = nodes.setdefault(index, CapellaNodeConfig())
        if field == "cpu":
            node.cpu = int(value)
        elif field == "ram":
            node.ram = int(value)
        elif field == "services":
            node.services = _parse_capella_services(value)
    return [nodes[key] for key in sorted(nodes)]


def build_capella_cluster_config(
    options: Mapping[str, str],
    nodes: Sequence[CapellaNodeConfig],
) -> ClusterConfig:
    _ = options
    config = ClusterConfig()
    if not nodes:
        return config.single_node(DEFAULT_CAPELLA_SERVICES)
    config.availability(AvailabilityType.SINGLE_ZONE)
    for node in nodes:
        config.add_service_group(
            ServiceGroupConfig()
            .with_cpu(node.cpu)
            .with_ram(node.ram)
            .with_num_of_nodes(1)
            .with_storage(100)
            .with_services(node.services)
        )
    return config


def calculate_server_quotas(
    node: ClusterNodeConfig,
    options: Mapping[str, str],
) -> Dict[str, int]:
    available_mib = int(math.floor(node.ram_gib * 1024 * 0.8))
    quota_service_count = sum(1 for service in node.services if not _is_query_service(service))
    if quota_service_count == 0:
        quota_service_count = 1
    default_quota = max(256, available_mib // quota_service_count)
    quotas: Dict[str, int] = {}
    for service in node.services:
        if _is_query_service(service):
            continue
        property_key = CouchbaseConfig.server_quota_key(service)
        quotas[_normalize_server_service(service)] = _read_quota_override(
            options, property_key, default_quota
        )
    return quotas


def to_rest_services(services: Sequence[str]) -> str:
    return ",".join(_to_rest_service(service) for service in services)


def initialize_single_node_cluster(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
    services: Sequence[str],
    quotas: Mapping[str, int],
    cluster_hostname: Optional[str] = None,
) -> None:
    resolved_hostname = cluster_init_hostname(cluster_hostname or endpoint.host)
    fields: MutableMapping[str, str] = {
        "hostname": resolved_hostname,
        "username": username,
        "password": password,
        "port": "SAME",
        "services": to_rest_services(services),
        "allowedHosts": allowed_hosts(resolved_hostname),
        "indexerStorageMode": "plasma",
    }
    _apply_quota_fields(fields, quotas)
    post_form(endpoint, None, None, "/clusterInit", fields)


def allowed_hosts(cluster_hostname: str) -> str:
    return cluster_hostname


def cluster_init_hostname(host: str) -> str:
    if not host or not host.strip():
        return "127.0.0.1"
    normalized = host.lower()
    if normalized == "localhost":
        return "127.0.0.1"
    if "." in normalized:
        return host
    return f"{host}.local"


def add_node_to_cluster(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
    node_host: str,
    services: Sequence[str],
) -> None:
    fields = {
        "hostname": node_host,
        "user": username,
        "password": password,
        "services": to_rest_services(services),
    }
    post_form(endpoint, username, password, "/controller/addNode", fields)


def rebalance_cluster(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
    node_hosts: Sequence[str],
) -> None:
    known_nodes = ",".join(f"ns_1@{host}" for host in node_hosts)
    post_form(
        endpoint,
        username,
        password,
        "/controller/rebalance",
        {"knownNodes": known_nodes},
    )


def wait_for_cluster(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
    retries: int = 60,
) -> None:
    rest = _admin_client(endpoint, username, password)
    for _ in range(retries):
        try:
            response = rest.get("/pools/default").validate().json()
            if isinstance(response, dict) and response.get("nodes"):
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise ClusterCreateError(
        f"Timed out waiting for Couchbase cluster at {endpoint.host}:{endpoint.admin_port}"
    )


def wait_for_rebalance_complete(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
) -> None:
    rest = _admin_client(endpoint, username, password)
    for _ in range(120):
        try:
            if not _is_rebalance_in_progress(rest):
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise ClusterCreateError(
        f"Timed out waiting for rebalance to complete at {endpoint.host}:{endpoint.admin_port}"
    )


def wait_for_query_ready(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
) -> None:
    if is_query_ready(endpoint, username, password):
        return
    for _ in range(60):
        time.sleep(2)
        if is_query_ready(endpoint, username, password):
            return
    raise ClusterCreateError(
        f"Timed out waiting for query service at {endpoint.host}:{endpoint.query_port}"
    )


def is_query_ready(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
) -> bool:
    try:
        _form_client(endpoint, username, password, endpoint.query_port).post_form(
            "/query/service",
            {"statement": "SELECT 1"},
        ).validate()
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_for_cluster_services(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
) -> None:
    rest = _admin_client(endpoint, username, password)
    for _ in range(120):
        try:
            response = rest.get("/pools/default").validate().json()
            if _services_running(response, "kv", "n1ql", "index"):
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise ClusterCreateError(
        f"Timed out waiting for Couchbase cluster services at {endpoint.host}:{endpoint.admin_port}"
    )


def is_cluster_initialized(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
) -> bool:
    rest = _admin_client(endpoint, username, password)
    try:
        response = rest.get("/pools/default").validate().json()
        return isinstance(response, dict) and bool(response.get("nodes"))
    except Exception:  # noqa: BLE001
        try:
            response = (
                _admin_client(endpoint, None, None).get("/pools").validate().json()
            )
            return isinstance(response, dict) and bool(response.get("pools"))
        except Exception:  # noqa: BLE001
            return False


def is_node_api_ready(endpoint: ClusterRestEndpoint) -> bool:
    try:
        _form_client(endpoint, None, None, endpoint.admin_port).get("/pools").validate()
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_for_node_api(
    endpoint: ClusterRestEndpoint,
    retries: int = 60,
) -> None:
    for _ in range(retries):
        if is_node_api_ready(endpoint):
            logger.debug(
                "Node API ready at %s:%s/pools",
                endpoint.host,
                endpoint.admin_port,
            )
            return
        time.sleep(2)
    scheme = "https" if endpoint.use_ssl else "http"
    raise ClusterCreateError(
        f"Timed out waiting for Couchbase API at "
        f"{scheme}://{endpoint.host}:{endpoint.admin_port}/pools"
    )


def wait_for_nodes_api(
    nodes: Sequence[ClusterNodeConfig],
    use_ssl: bool,
    use_ext_api: bool = False,
    retries: int = 60,
) -> None:
    for node in nodes:
        endpoint = node_endpoint(node, use_ssl, use_ext_api)
        logger.debug(
            "Waiting for node API on %s (ssl=%s, ext_api=%s)",
            endpoint.host,
            use_ssl,
            use_ext_api,
        )
        wait_for_node_api(endpoint, retries=retries)


def post_form(
    endpoint: ClusterRestEndpoint,
    username: Optional[str],
    password: Optional[str],
    path: str,
    fields: Mapping[str, str],
) -> None:
    normalized = path if path.startswith("/") else f"/{path}"
    rest = _form_client(endpoint, username, password, endpoint.admin_port)
    try:
        rest.post_form(normalized, dict(fields)).validate()
    except Exception as exc:  # noqa: BLE001
        raise ClusterCreateError(
            f"HTTP {rest.response_code} from {normalized}: {exc}"
        ) from exc


def setup_alternate_address(
    endpoint: ClusterRestEndpoint,
    username: str,
    password: str,
    alternate_hostname: str,
    ports: Optional[Mapping[str, int]] = None,
) -> None:
    fields: MutableMapping[str, str] = {"hostname": alternate_hostname}
    if ports:
        for service, port in ports.items():
            fields[_to_rest_service(service)] = str(port)
    path = "/node/controller/setupAlternateAddresses/external"
    rest = _form_client(endpoint, username, password, endpoint.admin_port)
    try:
        rest.put_form(path, dict(fields)).validate()
    except Exception as exc:  # noqa: BLE001
        raise ClusterCreateError(
            f"HTTP {rest.response_code} from {path}: {exc}"
        ) from exc


def apply_alternate_addresses(
    nodes: Sequence[ClusterNodeConfig],
    username: str,
    password: str,
    use_ssl: bool,
    use_ext_api: bool = False,
) -> None:
    for node in nodes:
        if not node.alternate_address:
            continue
        endpoint = node_endpoint(node, use_ssl, use_ext_api)
        logger.debug(
            "Setting alternate address %s on node %s",
            node.alternate_address,
            endpoint.host,
        )
        setup_alternate_address(
            endpoint,
            username,
            password,
            node.alternate_address,
            node.alternate_ports or None,
        )


def _is_rebalance_in_progress(rest: RestAPI) -> bool:
    progress = rest.get("/pools/default/rebalanceProgress").validate().json()
    if isinstance(progress, dict) and progress.get("status") is not None:
        status = str(progress.get("status"))
        if status.lower() == "running":
            return True
        if status.lower() == "none":
            return False

    pools = rest.get("/pools/default").validate().json()
    if isinstance(pools, dict) and pools.get("rebalanceStatus") is not None:
        status = str(pools.get("rebalanceStatus"))
        if status and status.lower() != "none":
            return True

    tasks = rest.get("/pools/default/tasks").validate().json()
    if isinstance(tasks, list):
        for task in tasks:
            if (
                isinstance(task, dict)
                and task.get("type") == "rebalance"
                and str(task.get("status", "")).lower() == "running"
            ):
                return True
    return False


def _services_running(pools: object, *rest_services: str) -> bool:
    if not isinstance(pools, dict):
        return False
    nodes = pools.get("nodes") or []
    if not nodes:
        return False
    services = nodes[0].get("services")
    if services is None:
        return False
    return all(_service_enabled(services, service) for service in rest_services)


def _service_enabled(services: object, service: str) -> bool:
    if isinstance(services, list):
        return service in services
    if not isinstance(services, dict) or service not in services:
        return False
    value = services.get(service)
    return bool(value is not None and str(value) and str(value).lower() != "notrunning")


def _apply_quota_fields(fields: MutableMapping[str, str], quotas: Mapping[str, int]) -> None:
    if "data" in quotas:
        fields["memoryQuota"] = str(quotas["data"])
    if "index" in quotas:
        fields["indexMemoryQuota"] = str(quotas["index"])
    if "fts" in quotas:
        fields["ftsMemoryQuota"] = str(quotas["fts"])
    if "eventing" in quotas:
        fields["eventingMemoryQuota"] = str(quotas["eventing"])
    if "analytics" in quotas:
        fields["cbasMemoryQuota"] = str(quotas["analytics"])


def _read_quota_override(
    options: Mapping[str, str],
    property_key: str,
    default_quota: int,
) -> int:
    value = options.get(property_key)
    if value is None or not value.strip():
        return default_quota
    return int(value)


def parse_alternate_ports(value: Optional[str]) -> Dict[str, int]:
    ports: Dict[str, int] = {}
    if not value or not value.strip():
        return ports
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                f"Invalid alternate port {item!r}; expected service:port pairs"
            )
        service, port_text = item.split(":", 1)
        ports[_to_rest_service(service.strip())] = int(port_text.strip())
    return ports


def _parse_services(value: Optional[str], default_services: Sequence[str]) -> List[str]:
    if not value or not value.strip():
        return list(default_services)
    return [_normalize_server_service(part.strip()) for part in value.split(",") if part.strip()]


def _parse_capella_services(value: Optional[str]) -> List[str]:
    if not value or not value.strip():
        return list(DEFAULT_CAPELLA_SERVICES)
    return [_normalize_capella_service(part.strip()) for part in value.split(",") if part.strip()]


def _normalize_server_service(service: str) -> str:
    lowered = service.lower()
    mapping = {
        "kv": "data",
        "data": "data",
        "n1ql": "query",
        "query": "query",
        "index": "index",
        "fts": "fts",
        "search": "fts",
        "eventing": "eventing",
        "cbas": "analytics",
        "analytics": "analytics",
    }
    return mapping.get(lowered, lowered)


def _normalize_capella_service(service: str) -> str:
    lowered = service.lower()
    mapping = {
        "kv": "data",
        "data": "data",
        "n1ql": "query",
        "query": "query",
        "index": "index",
        "fts": "search",
        "search": "search",
        "eventing": "eventing",
        "cbas": "analytics",
        "analytics": "analytics",
    }
    return mapping.get(lowered, lowered)


def _to_rest_service(service: str) -> str:
    normalized = _normalize_server_service(service)
    mapping = {
        "data": "kv",
        "query": "n1ql",
        "index": "index",
        "fts": "fts",
        "eventing": "eventing",
        "analytics": "cbas",
    }
    return mapping.get(normalized, service)


def _is_query_service(service: str) -> bool:
    return _normalize_server_service(service) == "query"


def _admin_client(
    endpoint: ClusterRestEndpoint,
    username: Optional[str],
    password: Optional[str],
) -> RestAPI:
    return _form_client(endpoint, username, password, endpoint.admin_port)


def _form_client(
    endpoint: ClusterRestEndpoint,
    username: Optional[str],
    password: Optional[str],
    port: int,
) -> RestAPI:
    if username is None:
        auth = NoAuth()
    else:
        auth = BasicAuth(username, password or "")
    return RestAPI(
        auth,
        hostname=endpoint.host,
        use_ssl=endpoint.use_ssl,
        verify=False,
        port=port,
    )
