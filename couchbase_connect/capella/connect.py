"""Connect to a cappella cluster."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import timedelta
from typing import Optional

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.exceptions import AmbiguousTimeoutException, UnAmbiguousTimeoutException
from couchbase.options import ClusterOptions, ClusterTimeoutOptions
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

logger = logging.getLogger(__name__)

_TEMP_CERT_FILES: list[str] = []


def normalize_connect_string(connect_string: str) -> str:
    value = (connect_string or "").strip()
    if not value:
        return value
    if value.startswith("couchbases://") or value.startswith("couchbase://"):
        return value
    return f"couchbases://{value}"


def connect_cluster(
    connect_string: str,
    username: str,
    password: str,
    certificate_pem: Optional[str] = None,
    kv_endpoints: int = 8,
    kv_timeout: int = 5,
    connect_timeout: int = 15,
    query_timeout: int = 75,
) -> Cluster:
    connect_string = normalize_connect_string(connect_string)
    if not connect_string:
        raise ValueError("Capella connection string is required")

    timeout_opts = _build_timeout_options(kv_timeout, connect_timeout, query_timeout)

    auth_kwargs: dict = {}
    if certificate_pem:
        auth_kwargs["cert_path"] = _write_cert_tempfile(certificate_pem)

    authenticator = PasswordAuthenticator(username, password, **auth_kwargs)
    options = _build_cluster_options(authenticator, timeout_opts)

    try:
        options.apply_profile("wan_development")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Unable to apply wan_development profile: %s", exc)

    _ = kv_endpoints

    cluster = _cluster_connect_with_retry(connect_string, options)

    try:
        cluster.wait_until_ready(timedelta(seconds=max(connect_timeout, 20)))
    except Exception:  # noqa: BLE001
        try:
            cluster.ping()
        except Exception as exc:
            logger.debug("Cluster ping after connect failed: %s", exc)

    logger.debug("Connected to %s", connect_string)
    return cluster


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.5),
    retry=retry_if_exception_type(
        (UnAmbiguousTimeoutException, AmbiguousTimeoutException)
    ),
    before_sleep=before_sleep_log(logger, logging.DEBUG),
)
def _cluster_connect_with_retry(connect_string: str, options: ClusterOptions) -> Cluster:
    cluster = Cluster.connect(connect_string, options)
    cluster.ping()
    return cluster


def _build_timeout_options(
    kv_timeout: int, connect_timeout: int, query_timeout: int
) -> ClusterTimeoutOptions:
    kwargs = {
        "kv_timeout": timedelta(seconds=max(kv_timeout, 20)),
        "connect_timeout": timedelta(seconds=max(connect_timeout, 20)),
        "query_timeout": timedelta(seconds=max(query_timeout, 120)),
        "bootstrap_timeout": timedelta(seconds=120),
        "dns_srv_timeout": timedelta(seconds=20),
        "resolve_timeout": timedelta(seconds=20),
        "management_timeout": timedelta(seconds=120),
    }
    try:
        return ClusterTimeoutOptions(**kwargs)
    except TypeError:
        return ClusterTimeoutOptions(
            kv_timeout=kwargs["kv_timeout"],
            connect_timeout=kwargs["connect_timeout"],
            query_timeout=kwargs["query_timeout"],
        )


def _build_cluster_options(
    authenticator: PasswordAuthenticator,
    timeout_opts: ClusterTimeoutOptions,
) -> ClusterOptions:
    try:
        return ClusterOptions(
            authenticator,
            timeout_options=timeout_opts,
            enable_tls=True,
        )
    except TypeError:
        return ClusterOptions(authenticator, timeout_options=timeout_opts)


def disconnect_cluster(cluster: Cluster) -> None:
    try:
        cluster.close()
    except Exception as exc:
        logger.warning("Cluster disconnect did not complete cleanly: %s", exc)
    finally:
        _cleanup_temp_certs()


def _write_cert_tempfile(certificate_pem: str) -> str:
    fd, path = tempfile.mkstemp(prefix="capella-cert-", suffix=".pem")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(certificate_pem)
            if not certificate_pem.endswith("\n"):
                handle.write("\n")
    except Exception:
        os.close(fd)
        raise
    _TEMP_CERT_FILES.append(path)
    return path


def _cleanup_temp_certs() -> None:
    while _TEMP_CERT_FILES:
        path = _TEMP_CERT_FILES.pop()
        try:
            os.unlink(path)
        except OSError:
            pass
