"""Typer CLI (`cbctl`) for Couchbase cluster and keyspace provisioning."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import typer

from couchbase_connect import cluster_create
from couchbase_connect.config import CouchbaseConfig
from couchbase_connect.server import Server

DEFAULT_SERVICES = ",".join(cluster_create.DEFAULT_SERVER_SERVICES)
DEFAULT_RAM_GIB = 4

NodeSpec = Tuple[str, List[str], int, Optional[str], dict[str, int]]

app = typer.Typer(
    name="cbctl",
    help="Provision Couchbase Server clusters, buckets, scopes, and collections.",
    no_args_is_help=True,
)
cluster_app = typer.Typer(help="Cluster operations.", no_args_is_help=True)
bucket_app = typer.Typer(help="Bucket operations.", no_args_is_help=True)
scope_app = typer.Typer(help="Scope operations.", no_args_is_help=True)
collection_app = typer.Typer(help="Collection operations.", no_args_is_help=True)

app.add_typer(cluster_app, name="cluster")
app.add_typer(bucket_app, name="bucket")
app.add_typer(scope_app, name="scope")
app.add_typer(collection_app, name="collection")


def _parse_alternate_fragment(
    fragment: str,
) -> Tuple[Optional[str], dict[str, int]]:
    text = fragment.strip()
    if not text:
        return None, {}
    if ";" in text:
        host, ports_text = text.split(";", 1)
        return host.strip() or None, cluster_create.parse_alternate_ports(ports_text)
    return text, {}


def _parse_node_spec(
    spec: str,
    default_services: Sequence[str],
    default_ram: int,
) -> NodeSpec:
    host_part = spec
    services: List[str] = list(default_services)
    ram = default_ram
    alternate_address: Optional[str] = None
    alternate_ports: dict[str, int] = {}

    if "#" in host_part:
        host_part, alternate_text = host_part.rsplit("#", 1)
        alternate_address, alternate_ports = _parse_alternate_fragment(alternate_text)

    if "@" in host_part:
        host_part, ram_text = host_part.rsplit("@", 1)
        if not ram_text.strip().isdigit():
            raise typer.BadParameter(
                f"Invalid RAM in node spec {spec!r}; "
                "expected HOST[=SERVICES][@RAM][#ALTERNATE]"
            )
        ram = int(ram_text.strip())

    if "=" in host_part:
        host, services_text = host_part.split("=", 1)
        parsed = [part.strip() for part in services_text.split(",") if part.strip()]
        if not parsed:
            raise typer.BadParameter(
                f"Invalid services in node spec {spec!r}; "
                "expected HOST[=SERVICES][@RAM][#ALTERNATE]"
            )
        services = parsed
    else:
        host = host_part

    host = host.strip()
    if not host:
        raise typer.BadParameter(
            f"Invalid node spec {spec!r}; "
            "expected HOST[=SERVICES][@RAM][#ALTERNATE]"
        )
    return host, services, ram, alternate_address, alternate_ports


def _build_server_options(
    nodes: Sequence[NodeSpec],
    ext_api: bool = False,
) -> dict[str, str]:
    options: dict[str, str] = {}
    for index, (host, services, ram, alternate, ports) in enumerate(nodes):
        options[f"couchbase.server.{index}.ip"] = host
        options[f"couchbase.server.{index}.ram"] = str(ram)
        options[f"couchbase.server.{index}.services"] = ",".join(services)
        if alternate:
            options[f"couchbase.server.{index}.alternateAddress"] = alternate
        if ports:
            options[f"couchbase.server.{index}.alternatePorts"] = ",".join(
                f"{service}:{port}" for service, port in ports.items()
            )
    if ext_api:
        options[CouchbaseConfig.COUCHBASE_SERVER_EXT_API] = "true"
    return options


def _connection_config(
    host: str,
    username: str,
    password: str,
    ssl: bool,
    bucket: Optional[str] = None,
    scope: Optional[str] = None,
    collection: Optional[str] = None,
    network: Optional[str] = None,
    connect_timeout: Optional[int] = None,
) -> CouchbaseConfig:
    config = (
        CouchbaseConfig()
        .host(host)
        .with_username(username)
        .with_password(password)
        .ssl(ssl)
    )
    if bucket:
        config = config.bucket(bucket)
    if scope:
        config = config.scope(scope)
    if collection:
        config = config.collection(collection)
    if network is not None:
        config = config.with_network(network)
    if connect_timeout is not None:
        config = config.with_connect_timeout(connect_timeout)
    return config


def _connected_server(config: CouchbaseConfig) -> Server:
    db = Server.get_instance()
    db.connect(config)
    return db


def _resolve_network_option(*, external: bool, internal: bool) -> Optional[str]:
    if external and internal:
        raise typer.BadParameter("Use either --external or --internal, not both")
    if external:
        return "external"
    if internal:
        return "default"
    return None


TEST_BUCKET = "__test"
TEST_DOCUMENT_ID = "cbctl-cluster-test"
TEST_DOCUMENT = {"ok": True, "source": "cbctl cluster test"}
DEFAULT_CLUSTER_TEST_TIMEOUT = 5


def _run_cluster_connectivity_test(
    db: Server,
    bucket: Optional[str] = None,
) -> None:
    manage_bucket = bucket is None
    target_bucket = TEST_BUCKET if manage_bucket else bucket
    assert target_bucket is not None

    if manage_bucket:
        if db.is_bucket(target_bucket):
            db.drop_bucket(target_bucket)
        db.create_bucket(target_bucket, quota=128, replicas=0)
    elif not db.is_bucket(target_bucket):
        raise RuntimeError(f"Bucket {target_bucket!r} does not exist")

    last_error: Optional[Exception] = None
    for _ in range(10):
        try:
            db.connect_keyspace(target_bucket, "_default", "_default")
            db.upsert(TEST_DOCUMENT_ID, TEST_DOCUMENT)
            fetched = db.get(TEST_DOCUMENT_ID)
            if fetched != TEST_DOCUMENT:
                raise RuntimeError(
                    f"Test document mismatch: expected {TEST_DOCUMENT!r}, got {fetched!r}"
                )
            if manage_bucket:
                db.drop_bucket(target_bucket)
            return
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Cluster KV test failed after retries: {last_error}")


@cluster_app.command("create")
def cluster_create_cmd(
    host: Optional[str] = typer.Option(
        None,
        "--host",
        help="Hostname or IP for a single-node cluster when --node is omitted.",
    ),
    node: Optional[List[str]] = typer.Option(
        None,
        "--node",
        "-n",
        help=(
            "Node spec for multi-dimensional scaling: "
            "HOST or HOST=SERVICES or HOST=SERVICES@RAM or HOST@RAM, "
            "optionally with #ALTERNATE or #ALTERNATE;kv:9000,n1ql:9050. "
            "Repeat for each node. "
            f"SERVICES default to {DEFAULT_SERVICES}; RAM defaults to {DEFAULT_RAM_GIB} GiB."
        ),
    ),
    services: str = typer.Option(
        DEFAULT_SERVICES,
        "--services",
        "-s",
        help="Default services when a node spec omits SERVICES.",
    ),
    ram: int = typer.Option(
        DEFAULT_RAM_GIB,
        "--ram",
        help="Default RAM quota in GiB when a node spec omits @RAM.",
    ),
    alternate_address: Optional[str] = typer.Option(
        None,
        "--alternate-address",
        "-a",
        help=(
            "External alternate address for a single-node cluster "
            "(when --node is omitted). For multi-node, embed #ALTERNATE in --node."
        ),
    ),
    ext_api: bool = typer.Option(
        False,
        "--ext-api/--no-ext-api",
        help=(
            "Use each node's alternate address for management REST API calls "
            "when an alternate address is configured."
        ),
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER,
        "--username",
        "-u",
        help="Administrator username.",
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD,
        "--password",
        "-p",
        help="Administrator password.",
    ),
    ssl: bool = typer.Option(
        False,
        "--ssl/--no-ssl",
        help="Use TLS for management endpoints (default: no TLS).",
    ),
) -> None:
    """Create and initialize a Couchbase Server cluster."""
    default_services = [part.strip() for part in services.split(",") if part.strip()]
    if not default_services:
        raise typer.BadParameter("At least one service is required")

    if node:
        if alternate_address:
            raise typer.BadParameter(
                "Use #ALTERNATE in --node instead of --alternate-address "
                "when specifying multiple nodes"
            )
        nodes = [_parse_node_spec(spec, default_services, ram) for spec in node]
    else:
        alt_host, alt_ports = _parse_alternate_fragment(alternate_address or "")
        nodes = [
            (
                host or CouchbaseConfig.DEFAULT_HOSTNAME,
                default_services,
                ram,
                alt_host,
                alt_ports,
            )
        ]

    if ext_api and not any(item[3] for item in nodes):
        raise typer.BadParameter(
            "--ext-api requires an alternate address on at least one node"
        )

    # Prefer alternate address for CouchbaseConfig.host when --ext-api is set.
    primary_host = nodes[0][0]
    if ext_api and nodes[0][3]:
        primary_host = nodes[0][3]
    config = _connection_config(primary_host, username, password, ssl)
    options = _build_server_options(nodes, ext_api=ext_api)

    db = Server.get_instance()
    try:
        created = db.create_cluster(config, options)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Failed to create cluster: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not created:
        return
    hosts = ", ".join(item[0] for item in nodes)
    typer.echo(f"Cluster created on {hosts}")


@cluster_app.command("exists")
def cluster_exists_cmd(
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME, "--host", help="Cluster hostname or IP."
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER, "--username", "-u", help="Administrator username."
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD, "--password", "-p", help="Administrator password."
    ),
    ssl: bool = typer.Option(
        False, "--ssl/--no-ssl", help="Use TLS when connecting (default: no TLS)."
    ),
) -> None:
    """Print whether a Couchbase Server cluster is configured."""
    config = _connection_config(host, username, password, ssl)
    typer.echo(str(Server.get_instance().cluster_exists(config)).lower())


@cluster_app.command("map")
def cluster_map_cmd(
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME, "--host", help="Cluster hostname or IP."
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER, "--username", "-u", help="Administrator username."
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD, "--password", "-p", help="Administrator password."
    ),
    ssl: bool = typer.Option(
        False, "--ssl/--no-ssl", help="Use TLS when connecting (default: no TLS)."
    ),
) -> None:
    """Print the cluster host map from the management REST API."""
    config = _connection_config(host, username, password, ssl)
    try:
        typer.echo(Server.get_instance().cluster_map(config))
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Failed to read cluster map: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@cluster_app.command("test")
def cluster_test_cmd(
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME, "--host", help="Cluster hostname or IP."
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER, "--username", "-u", help="Administrator username."
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD, "--password", "-p", help="Administrator password."
    ),
    ssl: bool = typer.Option(
        False, "--ssl/--no-ssl", help="Use TLS when connecting (default: no TLS)."
    ),
    bucket: Optional[str] = typer.Option(
        None,
        "--bucket",
        "-b",
        help=(
            "Existing bucket for put/get only. "
            "When omitted, create and delete a temporary __test bucket."
        ),
    ),
    external: bool = typer.Option(
        False,
        "--external",
        help="Force SDK network resolution to external alternate addresses.",
    ),
    internal: bool = typer.Option(
        False,
        "--internal",
        help="Force SDK network resolution to internal (default) addresses.",
    ),
    timeout: int = typer.Option(
        DEFAULT_CLUSTER_TEST_TIMEOUT,
        "--timeout",
        help="SDK connect timeout in seconds (default: 5).",
    ),
) -> None:
    """Connect and verify KV access via put/get.

    By default creates and deletes a temporary __test bucket. Pass --bucket to
    reuse an existing bucket and skip bucket create/delete.
    """
    if timeout <= 0:
        raise typer.BadParameter("--timeout must be a positive integer")
    network = _resolve_network_option(external=external, internal=internal)
    config = _connection_config(
        host,
        username,
        password,
        ssl,
        bucket=bucket,
        network=network,
        connect_timeout=timeout,
    )
    db = Server.get_instance()
    db.disconnect()
    manage_bucket = bucket is None
    try:
        db.connect(config)
        typer.echo(f"Connected to {host}")
        _run_cluster_connectivity_test(db, bucket=bucket)
        typer.echo("Cluster test passed")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Cluster test failed: {exc}", err=True)
        if manage_bucket:
            try:
                if db.cluster is not None and db.is_bucket(TEST_BUCKET):
                    db.drop_bucket(TEST_BUCKET)
            except Exception:  # noqa: BLE001
                pass
        raise typer.Exit(code=1) from exc
    finally:
        db.disconnect()


@bucket_app.command("create")
def bucket_create_cmd(
    name: str = typer.Argument(..., help="Bucket name."),
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME,
        "--host",
        help="Cluster hostname or IP.",
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER,
        "--username",
        "-u",
        help="Administrator username.",
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD,
        "--password",
        "-p",
        help="Administrator password.",
    ),
    quota: int = typer.Option(128, "--quota", help="RAM quota in MiB."),
    replicas: int = typer.Option(0, "--replicas", help="Number of replicas."),
    ssl: bool = typer.Option(
        False,
        "--ssl/--no-ssl",
        help="Use TLS when connecting (default: no TLS).",
    ),
) -> None:
    config = _connection_config(host, username, password, ssl, bucket=name)
    db = _connected_server(config)
    try:
        db.create_bucket(name, quota=quota, replicas=replicas)
        typer.echo(f"Bucket {name!r} created")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Failed to create bucket: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        db.disconnect()


@bucket_app.command("exists")
def bucket_exists_cmd(
    name: str = typer.Argument(..., help="Bucket name."),
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME, "--host", help="Cluster hostname or IP."
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER, "--username", "-u", help="Administrator username."
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD, "--password", "-p", help="Administrator password."
    ),
    ssl: bool = typer.Option(
        False, "--ssl/--no-ssl", help="Use TLS when connecting (default: no TLS)."
    ),
) -> None:
    """Print whether a bucket exists."""
    db = _connected_server(_connection_config(host, username, password, ssl))
    try:
        typer.echo(str(db.bucket_exists(name)).lower())
    finally:
        db.disconnect()


@scope_app.command("create")
def scope_create_cmd(
    name: str = typer.Argument(..., help="Scope name."),
    bucket: str = typer.Option(..., "--bucket", "-b", help="Parent bucket name."),
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME,
        "--host",
        help="Cluster hostname or IP.",
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER,
        "--username",
        "-u",
        help="Administrator username.",
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD,
        "--password",
        "-p",
        help="Administrator password.",
    ),
    ssl: bool = typer.Option(
        False,
        "--ssl/--no-ssl",
        help="Use TLS when connecting (default: no TLS).",
    ),
) -> None:
    config = _connection_config(host, username, password, ssl, bucket=bucket, scope=name)
    db = _connected_server(config)
    try:
        db.create_scope(bucket, name)
        typer.echo(f"Scope {name!r} created in bucket {bucket!r}")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Failed to create scope: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        db.disconnect()


@scope_app.command("exists")
def scope_exists_cmd(
    name: str = typer.Argument(..., help="Scope name."),
    bucket: str = typer.Option(..., "--bucket", "-b", help="Parent bucket name."),
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME, "--host", help="Cluster hostname or IP."
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER, "--username", "-u", help="Administrator username."
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD, "--password", "-p", help="Administrator password."
    ),
    ssl: bool = typer.Option(
        False, "--ssl/--no-ssl", help="Use TLS when connecting (default: no TLS)."
    ),
) -> None:
    """Print whether a scope exists."""
    db = _connected_server(_connection_config(host, username, password, ssl))
    try:
        typer.echo(str(db.scope_exists(bucket, name)).lower())
    finally:
        db.disconnect()


@collection_app.command("create")
def collection_create_cmd(
    name: str = typer.Argument(..., help="Collection name."),
    bucket: str = typer.Option(..., "--bucket", "-b", help="Parent bucket name."),
    scope: str = typer.Option(..., "--scope", "-s", help="Parent scope name."),
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME,
        "--host",
        help="Cluster hostname or IP.",
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER,
        "--username",
        "-u",
        help="Administrator username.",
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD,
        "--password",
        "-p",
        help="Administrator password.",
    ),
    ssl: bool = typer.Option(
        False,
        "--ssl/--no-ssl",
        help="Use TLS when connecting (default: no TLS).",
    ),
) -> None:
    config = _connection_config(
        host, username, password, ssl, bucket=bucket, scope=scope, collection=name
    )
    db = _connected_server(config)
    try:
        db.create_collection(bucket, scope, name)
        typer.echo(
            f"Collection {name!r} created in bucket {bucket!r} scope {scope!r}"
        )
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Failed to create collection: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        db.disconnect()


@collection_app.command("exists")
def collection_exists_cmd(
    name: str = typer.Argument(..., help="Collection name."),
    bucket: str = typer.Option(..., "--bucket", "-b", help="Parent bucket name."),
    scope: str = typer.Option(..., "--scope", "-s", help="Parent scope name."),
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME, "--host", help="Cluster hostname or IP."
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER, "--username", "-u", help="Administrator username."
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD, "--password", "-p", help="Administrator password."
    ),
    ssl: bool = typer.Option(
        False, "--ssl/--no-ssl", help="Use TLS when connecting (default: no TLS)."
    ),
) -> None:
    """Print whether a collection exists."""
    db = _connected_server(_connection_config(host, username, password, ssl))
    try:
        typer.echo(str(db.collection_exists(bucket, scope, name)).lower())
    finally:
        db.disconnect()


@app.command("import")
def import_json_lines_cmd(
    json_lines_file: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True, help="JSON Lines file to import."
    ),
    keyspace: str = typer.Argument(
        ..., help="Destination in bucket.scope.collection format."
    ),
    host: str = typer.Option(
        CouchbaseConfig.DEFAULT_HOSTNAME, "--host", help="Cluster hostname or IP."
    ),
    username: str = typer.Option(
        CouchbaseConfig.DEFAULT_USER, "--username", "-u", help="Administrator username."
    ),
    password: str = typer.Option(
        CouchbaseConfig.DEFAULT_PASSWORD, "--password", "-p", help="Administrator password."
    ),
    ssl: bool = typer.Option(
        False, "--ssl/--no-ssl", help="Use TLS when connecting (default: no TLS)."
    ),
) -> None:
    """Import JSON Lines into an empty collection."""
    parts = keyspace.split(".")
    if len(parts) != 3 or not all(parts):
        raise typer.BadParameter(
            "Keyspace must use bucket.scope.collection format", param_hint="keyspace"
        )
    bucket, scope, collection = parts
    config = _connection_config(
        host, username, password, ssl, bucket, scope, collection
    )
    db = _connected_server(config)
    try:
        db.ensure_collection(bucket, scope, collection)
        if not db.collection_is_empty(bucket, scope, collection):
            typer.echo("Collection not empty", err=True)
            return
        imported = db.populate_collection(
            json_lines_file, bucket, scope, collection
        )
        typer.echo(f"Imported {imported} documents")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Failed to import JSON Lines file: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        db.disconnect()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
