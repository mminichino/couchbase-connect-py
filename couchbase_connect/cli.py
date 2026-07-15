"""Typer CLI (`cbctl`) for Couchbase cluster and keyspace provisioning."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import typer

from couchbase_connect import cluster_create
from couchbase_connect.config import CouchbaseConfig
from couchbase_connect.server import Server

DEFAULT_SERVICES = ",".join(cluster_create.DEFAULT_SERVER_SERVICES)
DEFAULT_RAM_GIB = 4

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


def _parse_node_spec(
    spec: str,
    default_services: Sequence[str],
    default_ram: int,
) -> Tuple[str, List[str], int]:
    """Parse ``HOST[=SERVICES][@RAM]`` into host, services, and RAM GiB."""
    host_part = spec
    services: List[str] = list(default_services)
    ram = default_ram

    if "@" in host_part:
        host_part, ram_text = host_part.rsplit("@", 1)
        if not ram_text.strip().isdigit():
            raise typer.BadParameter(
                f"Invalid RAM in node spec {spec!r}; "
                "expected HOST, HOST=SERVICES, HOST=SERVICES@RAM, or HOST@RAM"
            )
        ram = int(ram_text.strip())

    if "=" in host_part:
        host, services_text = host_part.split("=", 1)
        parsed = [part.strip() for part in services_text.split(",") if part.strip()]
        if not parsed:
            raise typer.BadParameter(
                f"Invalid services in node spec {spec!r}; "
                "expected HOST, HOST=SERVICES, HOST=SERVICES@RAM, or HOST@RAM"
            )
        services = parsed
    else:
        host = host_part

    host = host.strip()
    if not host:
        raise typer.BadParameter(
            f"Invalid node spec {spec!r}; "
            "expected HOST, HOST=SERVICES, HOST=SERVICES@RAM, or HOST@RAM"
        )
    return host, services, ram


def _build_server_options(
    nodes: Sequence[Tuple[str, List[str], int]],
) -> dict[str, str]:
    options: dict[str, str] = {}
    for index, (host, services, ram) in enumerate(nodes):
        options[f"couchbase.server.{index}.ip"] = host
        options[f"couchbase.server.{index}.ram"] = str(ram)
        options[f"couchbase.server.{index}.services"] = ",".join(services)
    return options


def _connection_config(
    host: str,
    username: str,
    password: str,
    ssl: bool,
    bucket: Optional[str] = None,
    scope: Optional[str] = None,
    collection: Optional[str] = None,
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
    return config


def _connected_server(config: CouchbaseConfig) -> Server:
    db = Server.get_instance()
    db.connect(config)
    return db


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
            "HOST or HOST=SERVICES or HOST=SERVICES@RAM or HOST@RAM. "
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
        nodes = [
            _parse_node_spec(spec, default_services, ram) for spec in node
        ]
    else:
        nodes = [
            (
                host or CouchbaseConfig.DEFAULT_HOSTNAME,
                default_services,
                ram,
            )
        ]

    config = _connection_config(nodes[0][0], username, password, ssl)
    options = _build_server_options(nodes)

    db = Server.get_instance()
    try:
        db.create_cluster(config, options)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Failed to create cluster: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    hosts = ", ".join(item[0] for item in nodes)
    typer.echo(f"Cluster created on {hosts}")


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
    """Create a bucket on an existing cluster."""
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
    """Create a scope in a bucket."""
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
    """Create a collection in a scope."""
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
