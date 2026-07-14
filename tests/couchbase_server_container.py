"""Couchbase Server container helpers (mirrors Java CouchbaseServerContainer)."""

from __future__ import annotations

import logging
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional

from couchbase_connect.cluster_create import (
    ClusterRestEndpoint,
    is_cluster_initialized,
    is_query_ready,
)
from couchbase_connect.config import CouchbaseConfig

logger = logging.getLogger(__name__)

IMAGE = "couchbase/server:enterprise-8.0.1"
SHARED_CONTAINER_NAME = "couchbase-connect-py-test"
PORTS = [
    8091,
    8092,
    8093,
    8094,
    8095,
    8096,
    9123,
    11207,
    11210,
    11280,
    18091,
    18092,
    18093,
    18094,
    18095,
    18096,
    18097,
]

_shared_started = False


def shared_container() -> str:
    """Ensure the shared Couchbase container is running; return its name."""
    global _shared_started
    if _cluster_already_running():
        logger.info(
            "Reusing existing Couchbase cluster on %s:8091",
            CouchbaseConfig.DEFAULT_HOSTNAME,
        )
        _shared_started = True
        return SHARED_CONTAINER_NAME

    if _is_port_listening(8091) and _container_running(SHARED_CONTAINER_NAME):
        logger.info(
            "Reusing uninitialized Couchbase instance on %s:8091",
            CouchbaseConfig.DEFAULT_HOSTNAME,
        )
        _shared_started = True
        return SHARED_CONTAINER_NAME

    if not _container_exists(SHARED_CONTAINER_NAME):
        _create_shared()
    elif not _container_running(SHARED_CONTAINER_NAME):
        _docker(["start", SHARED_CONTAINER_NAME])
    _wait_for_ui(timeout_seconds=600)
    _shared_started = True
    return SHARED_CONTAINER_NAME


def start_dedicated_container() -> str:
    release_fixed_ports()
    name = f"{SHARED_CONTAINER_NAME}-dedicated"
    _docker_rm(name)
    _create_container(name)
    _wait_for_ui(timeout_seconds=600)
    return name


def stop_container(name: Optional[str]) -> None:
    if not name:
        return
    _docker(["stop", name], check=False)
    _docker(["rm", "-f", name], check=False)


def release_fixed_ports() -> None:
    stop_container(SHARED_CONTAINER_NAME)
    _stop_docker_containers_on_port(8091)


def _cluster_already_running() -> bool:
    endpoint = ClusterRestEndpoint.for_server(CouchbaseConfig.DEFAULT_HOSTNAME, False)
    if not _is_port_listening(8091):
        return False
    if not is_cluster_initialized(
        endpoint,
        CouchbaseConfig.DEFAULT_USER,
        CouchbaseConfig.DEFAULT_PASSWORD,
    ):
        return False
    return is_query_ready(
        endpoint,
        CouchbaseConfig.DEFAULT_USER,
        CouchbaseConfig.DEFAULT_PASSWORD,
    )


def _is_port_listening(port: int) -> bool:
    try:
        with socket.create_connection(
            (CouchbaseConfig.DEFAULT_HOSTNAME, port), timeout=0.5
        ):
            return True
    except OSError:
        return False


def _container_exists(name: str) -> bool:
    result = _docker(["inspect", name], check=False, capture=True)
    return result.returncode == 0


def _container_running(name: str) -> bool:
    result = _docker(
        ["inspect", "-f", "{{.State.Running}}", name],
        check=False,
        capture=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _create_shared() -> None:
    _create_container(SHARED_CONTAINER_NAME)


def _create_container(name: str) -> None:
    args = [
        "run",
        "-d",
        "--name",
        name,
        "--memory",
        "4g",
    ]
    for port in PORTS:
        args.extend(["-p", f"{port}:{port}"])
    args.append(IMAGE)
    logger.info("Starting Couchbase container %s from %s", name, IMAGE)
    _docker(args)


def _wait_for_ui(timeout_seconds: int = 600) -> None:
    deadline = time.time() + timeout_seconds
    url = f"http://{CouchbaseConfig.DEFAULT_HOSTNAME}:8091/ui/index.html"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    logger.info("Couchbase UI is ready")
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for Couchbase UI at {url}")


def _stop_docker_containers_on_port(port: int) -> None:
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"publish={port}"],
            check=False,
            capture_output=True,
            text=True,
        )
        for container_id in result.stdout.strip().splitlines():
            if not container_id.strip():
                continue
            logger.debug("Stopping container %s occupying port %s", container_id, port)
            _docker(["rm", "-f", container_id.strip()], check=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Unable to stop containers on port %s: %s", port, exc)


def _docker_rm(name: str) -> None:
    _docker(["rm", "-f", name], check=False)


def _docker(
    args: list[str],
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=capture,
        text=True,
    )
