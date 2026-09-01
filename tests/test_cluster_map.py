"""Unit tests for cluster host map formatting."""

from __future__ import annotations

import dns.resolver
from unittest.mock import patch

from couchbase_connect.base import format_cluster_map_text, lookup_srv_records


def test_format_cluster_map_text_includes_nodes() -> None:
    cluster_info = {
        "nodes": [
            {
                "configuredHostname": "node1.example.com",
                "version": "7.6.0-1234-enterprise",
                "os": "linux",
                "services": ["data", "index", "query"],
            }
        ]
    }
    text = format_cluster_map_text("cluster.example.com", [], cluster_info)
    assert "Cluster Host List:" in text
    assert "[01] node1.example.com" in text
    assert "[Services] data,index,query" in text
    assert "[version] 7.6.0-1234-enterprise" in text
    assert "[platform] linux" in text


def test_format_cluster_map_text_includes_external_addresses() -> None:
    cluster_info = {
        "nodes": [
            {
                "configuredHostname": "10.0.0.1",
                "version": "7.6.0-1234-enterprise",
                "os": "linux",
                "services": ["data"],
                "alternateAddresses": {
                    "external": {
                        "hostname": "public.example.com",
                        "ports": {"kv": 11210, "n1ql": 18093},
                    }
                },
            }
        ]
    }
    text = format_cluster_map_text("cluster.example.com", [], cluster_info)
    assert "[external]> public.example.com" in text
    assert "kv:11210" in text
    assert "n1ql:18093" in text


def test_format_cluster_map_text_includes_srv_records() -> None:
    srv_records = [
        {"hostname": "node1.cb.example.com", "address": "10.0.0.1"},
        {"hostname": "node2.cb.example.com", "address": "10.0.0.2"},
    ]
    text = format_cluster_map_text(
        "cluster.example.com",
        srv_records,
        {"nodes": []},
    )
    assert "Name cluster.example.com is a domain with SRV records:" in text
    assert " => node1.cb.example.com (10.0.0.1)" in text
    assert " => node2.cb.example.com (10.0.0.2)" in text


def test_lookup_srv_records_returns_empty_when_no_records() -> None:
    with patch(
        "dns.resolver.resolve",
        side_effect=dns.resolver.NXDOMAIN(),
    ):
        records = lookup_srv_records("missing.example.com", tls=False)
    assert records == []
