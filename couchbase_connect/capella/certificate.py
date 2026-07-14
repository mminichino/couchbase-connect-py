"""Capella cluster certificate resource."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from couchbase_connect.capella.exceptions import CapellaAPIError
from couchbase_connect.capella.models import CertificateResponse
from couchbase_connect.capella.utils import model_validate

if TYPE_CHECKING:
    from couchbase_connect.capella.cluster import CapellaCluster

logger = logging.getLogger(__name__)


def parse_x509_certificate(pem: str) -> Any:
    """Parse a PEM-encoded X.509 certificate.

    Uses the ``cryptography`` package when available; otherwise raises RuntimeError.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
    except ImportError as exc:
        raise RuntimeError(
            "cryptography package is required to parse X.509 certificates"
        ) from exc
    return x509.load_pem_x509_certificate(pem.encode("utf-8"), default_backend())


class CapellaCertificate:
    def __init__(self, cluster: "CapellaCluster") -> None:
        if cluster.cluster_data is None or cluster.cluster_data.id is None:
            raise RuntimeError("Cluster must be resolved before accessing certificates")
        self.cluster = cluster
        self.rest = cluster.rest
        self.endpoint = f"{cluster.endpoint}/{cluster.cluster_data.id}/certificates"
        self._certificate_pem: Optional[str] = None
        self._certificate: Any = None

    @classmethod
    def get_instance(cls, cluster: "CapellaCluster") -> "CapellaCertificate":
        service = cluster.get_certificate()
        if service is None:
            service = cls(cluster)
            cluster.certificate = service
        return service

    @property
    def certificate_pem(self) -> Optional[str]:
        return self._certificate_pem

    def get_certificate(self) -> Any:
        return self._certificate

    def set_certificate(self, certificate_pem: str) -> None:
        self._certificate_pem = certificate_pem
        try:
            self._certificate = parse_x509_certificate(certificate_pem)
        except Exception as exc:
            logger.debug("Unable to parse certificate: %s", exc)
            self._certificate = None

    def get_cluster_certificate(self) -> str:
        """Return the cluster CA certificate as a PEM string."""
        try:
            reply = self.rest.get(self.endpoint).validate().json()
            response = model_validate(CertificateResponse, reply)
            self._certificate_pem = response.certificate
            return response.certificate
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Cluster Certificate Error",
                exc,
            ) from exc
