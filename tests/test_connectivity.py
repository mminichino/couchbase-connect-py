"""Unit tests for Capella DNS SRV connectivity resolution."""

from __future__ import annotations

from unittest.mock import patch

from couchbase_connect.capella.connect import normalize_connect_string
from couchbase_connect.capella.connectivity import (
    CapellaConnectivity,
    HostPort,
    MANAGER_PORT_TLS,
)


def test_normalize_connect_string_adds_tls_scheme() -> None:
    assert (
        normalize_connect_string("cb.example.cloud.couchbase.com")
        == "couchbases://cb.example.cloud.couchbase.com"
    )


def test_normalize_connect_string_keeps_existing_scheme() -> None:
    assert (
        normalize_connect_string("couchbases://cb.example.cloud.couchbase.com")
        == "couchbases://cb.example.cloud.couchbase.com"
    )


def test_extract_hosts_from_bare_hostname() -> None:
    hosts = CapellaConnectivity._extract_hosts("cb.example.cloud.couchbase.com")
    assert hosts == [("cb.example.cloud.couchbase.com", None)]


def test_extract_hosts_from_connection_string() -> None:
    hosts = CapellaConnectivity._extract_hosts(
        "couchbases://cb.example.cloud.couchbase.com"
    )
    assert hosts == [("cb.example.cloud.couchbase.com", None)]


def test_resolve_targets_uses_srv_hostnames() -> None:
    connectivity = CapellaConnectivity(srv_lookup_timeout=0.01, srv_lookup_poll_interval=0.01)
    with patch.object(
        CapellaConnectivity,
        "lookup_srv_hostnames",
        return_value=["svc-1.example.com", "svc-2.example.com"],
    ):
        targets = connectivity.resolve_targets("cb.example.cloud.couchbase.com", tls=True)
    assert targets == [
        HostPort("svc-1.example.com", MANAGER_PORT_TLS),
        HostPort("svc-2.example.com", MANAGER_PORT_TLS),
    ]


def test_resolve_targets_falls_back_when_srv_empty() -> None:
    connectivity = CapellaConnectivity(srv_lookup_timeout=0.01, srv_lookup_poll_interval=0.01)
    with patch.object(CapellaConnectivity, "lookup_srv_hostnames", return_value=[]):
        targets = connectivity.resolve_targets("cb.example.cloud.couchbase.com", tls=True)
    assert targets == [HostPort("cb.example.cloud.couchbase.com", MANAGER_PORT_TLS)]


def test_check_connectivity_succeeds_via_srv_target() -> None:
    connectivity = CapellaConnectivity(srv_lookup_timeout=0.01, srv_lookup_poll_interval=0.01)
    with (
        patch.object(
            CapellaConnectivity,
            "lookup_srv_hostnames",
            return_value=["svc-1.example.com"],
        ),
        patch.object(CapellaConnectivity, "_can_connect", side_effect=[False, True]) as mock_connect,
    ):
        assert connectivity.check_connectivity(
            "cb.example.cloud.couchbase.com",
            timeout=5.0,
            poll_interval=0.01,
        )
    assert mock_connect.call_args_list[0].args == ("svc-1.example.com", MANAGER_PORT_TLS)


def test_explicit_port_skips_srv() -> None:
    connectivity = CapellaConnectivity()
    with patch.object(CapellaConnectivity, "lookup_srv_hostnames") as mock_srv:
        targets = connectivity.resolve_targets("host.example.com:18091", tls=True)
    mock_srv.assert_not_called()
    assert targets == [HostPort("host.example.com", 18091)]
