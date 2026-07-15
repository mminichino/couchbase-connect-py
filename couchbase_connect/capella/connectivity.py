"""TCP connectivity checks against Capella cluster manager ports."""

from __future__ import annotations

import logging
import re
import socket
import time
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import dns.exception
import dns.resolver

logger = logging.getLogger(__name__)

MANAGER_PORT_TLS = 18091
MANAGER_PORT_PLAIN = 8091
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_CONNECT_TIMEOUT = 3.0
DEFAULT_SRV_LOOKUP_TIMEOUT = 30.0
DEFAULT_SRV_LOOKUP_POLL_INTERVAL = 2.0

SRV_SERVICE_PLAIN = "_couchbase._tcp."
SRV_SERVICE_TLS = "_couchbases._tcp."


@dataclass(frozen=True)
class HostPort:
    host: str
    port: int


class CapellaConnectivity:

    def __init__(
        self,
        srv_lookup_timeout: float = DEFAULT_SRV_LOOKUP_TIMEOUT,
        srv_lookup_poll_interval: float = DEFAULT_SRV_LOOKUP_POLL_INTERVAL,
    ) -> None:
        self.srv_lookup_timeout = srv_lookup_timeout
        self.srv_lookup_poll_interval = srv_lookup_poll_interval

    def srv_lookup_retry(
        self, timeout: float, poll_interval: float
    ) -> "CapellaConnectivity":
        self.srv_lookup_timeout = timeout
        self.srv_lookup_poll_interval = poll_interval
        return self

    def check_connectivity(
        self,
        connect_string: str,
        tls: bool = True,
        timeout: float = 60.0,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> bool:
        targets = self.resolve_targets(connect_string, tls=tls)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for target in targets:
                if self._can_connect(target.host, target.port):
                    logger.debug("Connected to %s:%s", target.host, target.port)
                    return True
            refreshed = self.resolve_targets(connect_string, tls=tls, wait_for_srv=False)
            if refreshed:
                targets = refreshed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, remaining))
        logger.debug("Connectivity check failed for %s within %ss", connect_string, timeout)
        return False

    def resolve_targets(
        self,
        connect_string: str,
        tls: bool = True,
        *,
        wait_for_srv: bool = True,
    ) -> List[HostPort]:
        default_port = MANAGER_PORT_TLS if tls else MANAGER_PORT_PLAIN
        hosts = self._extract_hosts(connect_string)
        targets: List[HostPort] = []
        dns_srv_candidate = (
            hosts[0][0] if len(hosts) == 1 and hosts[0][1] is None else None
        )
        for host, port in hosts:
            if port is not None:
                targets.append(HostPort(host, port))
                continue
            if dns_srv_candidate is not None and host == dns_srv_candidate:
                targets.extend(
                    self._resolve_srv_targets(
                        host, tls, default_port, wait_for_srv=wait_for_srv
                    )
                )
            else:
                targets.append(HostPort(host, default_port))
        return targets or [HostPort(self._bare_hostname(connect_string), default_port)]

    def _resolve_srv_targets(
        self,
        hostname: str,
        tls: bool,
        default_port: int,
        *,
        wait_for_srv: bool = True,
    ) -> List[HostPort]:
        deadline = (
            time.monotonic() + self.srv_lookup_timeout
            if wait_for_srv
            else time.monotonic()
        )
        while True:
            try:
                hostnames = self.lookup_srv_hostnames(hostname, tls)
                if hostnames:
                    logger.debug("SRV lookup succeeded for %s", hostname)
                    return [HostPort(h, default_port) for h in hostnames]
                logger.debug("SRV lookup returned no records for %s", hostname)
            except (dns.exception.DNSException, OSError) as exc:
                logger.debug("SRV lookup failed for %s: %s", hostname, exc)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.srv_lookup_poll_interval, remaining))

        logger.debug("SRV lookup timed out for %s, falling back to hostname", hostname)
        return [HostPort(hostname, default_port)]

    @staticmethod
    def lookup_srv_hostnames(hostname: str, tls: bool = True) -> List[str]:
        service = (SRV_SERVICE_TLS if tls else SRV_SERVICE_PLAIN) + hostname
        answers = dns.resolver.resolve(service, "SRV")
        return [str(rdata.target).rstrip(".") for rdata in answers]

    @staticmethod
    def _extract_hosts(connect_string: str) -> List[tuple[str, Optional[int]]]:
        value = connect_string.strip()
        if "://" not in value:
            value = f"couchbases://{value}"
        parsed = urlparse(value)
        netloc = parsed.netloc or parsed.path
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        netloc = netloc.split("/", 1)[0]
        if not netloc:
            return []
        results: List[tuple[str, Optional[int]]] = []
        for part in netloc.split(","):
            part = part.strip()
            if not part:
                continue
            match = re.match(r"^\[([^]]+)](?::(\d+))?$", part)
            if match:
                results.append((match.group(1), int(match.group(2)) if match.group(2) else None))
                continue
            if part.count(":") == 1:
                host, port_str = part.split(":", 1)
                try:
                    results.append((host, int(port_str)))
                except ValueError:
                    results.append((part, None))
            else:
                results.append((part, None))
        return results

    @staticmethod
    def _bare_hostname(connect_string: str) -> str:
        hosts = CapellaConnectivity._extract_hosts(connect_string)
        if hosts:
            return hosts[0][0]
        return connect_string

    @staticmethod
    def _can_connect(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=DEFAULT_CONNECT_TIMEOUT):
                return True
        except OSError as exc:
            logger.debug("Unable to connect to %s:%s - %s", host, port, exc)
            return False
