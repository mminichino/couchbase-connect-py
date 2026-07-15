"""Unit and server tests for cluster create helpers."""

from __future__ import annotations

import pytest
from restfull.basic_auth import BasicAuth
from restfull.restapi import RestAPI

from couchbase_connect import CouchbaseConfig, Server, cluster_create
from couchbase_connect.cli import _parse_node_spec

HOST = "127.0.0.1"
ADMIN = CouchbaseConfig.DEFAULT_USER
PASSWORD = CouchbaseConfig.DEFAULT_PASSWORD
ALTERNATE = "localhost"


def test_parse_server_nodes_alternate_address_and_ports() -> None:
    nodes = cluster_create.parse_server_nodes(
        {
            "couchbase.server.0.ip": "10.0.0.1",
            "couchbase.server.0.ram": "4",
            "couchbase.server.0.services": "data,query",
            "couchbase.server.0.alternateAddress": "ext-0.example.com",
            "couchbase.server.0.alternatePorts": "kv:9000,query:9050",
            "couchbase.server.1.ip": "10.0.0.2",
            "couchbase.server.1.alternate": "ext-1.example.com",
            "couchbase.server.1.alternatePort.fts": "9200",
        }
    )
    assert len(nodes) == 2
    assert nodes[0].ip == "10.0.0.1"
    assert nodes[0].alternate_address == "ext-0.example.com"
    assert nodes[0].alternate_ports == {"kv": 9000, "n1ql": 9050}
    assert nodes[1].alternate_address == "ext-1.example.com"
    assert nodes[1].alternate_ports == {"fts": 9200}


def test_cli_parse_node_spec_with_alternate() -> None:
    host, services, ram, alternate, ports = _parse_node_spec(
        "10.0.0.1=data,index@8#ext.example.com;kv:9000,n1ql:9050",
        ["data", "index", "query", "fts"],
        4,
    )
    assert host == "10.0.0.1"
    assert services == ["data", "index"]
    assert ram == 8
    assert alternate == "ext.example.com"
    assert ports == {"kv": 9000, "n1ql": 9050}


@pytest.mark.server
@pytest.mark.usefixtures("server_container")
def test_create_cluster_with_alternate_address() -> None:
    db = Server.get_instance()
    config = (
        CouchbaseConfig()
        .host(HOST)
        .with_username(ADMIN)
        .with_password(PASSWORD)
        .ssl(False)
    )
    options = {
        "couchbase.server.0.ip": HOST,
        "couchbase.server.0.ram": "4",
        "couchbase.server.0.services": "data,index,query,fts",
        "couchbase.server.0.alternateAddress": ALTERNATE,
    }

    db.create_cluster(config, options)

    rest = RestAPI(
        BasicAuth(ADMIN, PASSWORD),
        hostname=HOST,
        use_ssl=False,
        verify=False,
        port=8091,
    )
    pools = rest.get("/pools/default").validate().json()
    assert isinstance(pools, dict)
    nodes = pools.get("nodes") or []
    assert nodes
    alternate = nodes[0].get("alternateAddresses") or {}
    external = alternate.get("external") or {}
    assert external.get("hostname") == ALTERNATE
