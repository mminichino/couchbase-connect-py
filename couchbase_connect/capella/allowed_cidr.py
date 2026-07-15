"""Capella allowed CIDR resource."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from restfull.exceptions import NotFoundError

from couchbase_connect.capella.exceptions import CapellaAPIError, CapellaNotFoundError
from couchbase_connect.capella.models import AllowedCIDRData, CreateAllowedCidrRequest
from couchbase_connect.capella.utils import dump_model, model_validate

if TYPE_CHECKING:
    from couchbase_connect.capella.cluster import CapellaCluster

logger = logging.getLogger(__name__)


class CapellaAllowedCIDR:
    def __init__(self, cluster: "CapellaCluster") -> None:
        if cluster.cluster_data is None or cluster.cluster_data.id is None:
            raise RuntimeError("Cluster must be resolved before accessing allowed CIDRs")
        self.cluster = cluster
        self.rest = cluster.rest
        self.endpoint = f"{cluster.endpoint}/{cluster.cluster_data.id}/allowedcidrs"
        self.cidr: Optional[AllowedCIDRData] = None

    @classmethod
    def get_instance(cls, cluster: "CapellaCluster") -> "CapellaAllowedCIDR":
        service = cluster.get_allowed_cidr()
        if service is None:
            service = cls(cluster)
            cluster.allowed_cidr = service
        return service

    def is_cidr(self, network: str) -> Optional[AllowedCIDRData]:
        for listed in self.list():
            if network == listed.cidr:
                return listed
        return None

    def create_allowed_cidr(self, network: str) -> AllowedCIDRData:
        check = self.is_cidr(network)
        if check is not None:
            logger.debug("CIDR %s already allowed", network)
            self.cidr = check
            return check

        logger.debug("Allowing access from network %s", network)
        parameters = CreateAllowedCidrRequest(
            cidr=network,
            comment="Automatically Created Allowed CIDR Block",
        )
        try:
            reply = self.rest.post(self.endpoint, dump_model(parameters)).validate().json()
            cidr_id = reply.get("id")
            try:
                self.cidr = self.get_by_id(cidr_id)
                assert self.cidr is not None
                return self.cidr
            except (CapellaNotFoundError, AssertionError) as exc:
                raise RuntimeError("Allowed CIDR creation failed") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Allowed CIDR Create Error",
                exc,
            ) from exc

    def delete(self) -> None:
        if self.cidr is None or self.cidr.id is None:
            return
        try:
            self.rest.delete(f"{self.endpoint}/{self.cidr.id}").validate()
            logger.debug("CIDR %s deleted", self.cidr.cidr)
            self.cidr = None
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Allowed CIDR Delete Error",
                exc,
            ) from exc

    def list(self) -> List[AllowedCIDRData]:
        try:
            items = (
                self.rest.get_paged(
                    self.endpoint,
                    "page",
                    "totalItems",
                    "last",
                    "perPage",
                    50,
                    "data",
                    "cursor",
                    "pages",
                )
                .validate()
                .json_list()
                .as_list
            )
            return [model_validate(AllowedCIDRData, item) for item in items]
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Allowed CIDR List Error",
                exc,
            ) from exc

    def get_by_name(self, network: str) -> AllowedCIDRData:
        if self.cidr is not None and network == self.cidr.cidr:
            return self.cidr
        for listed in self.list():
            if network == listed.cidr:
                return listed
        raise CapellaNotFoundError(f"Can not find allowed CIDR {network}")

    def get_by_id(self, cidr_id: str) -> AllowedCIDRData:
        if self.cidr is not None and self.cidr.id == cidr_id:
            return self.cidr
        try:
            reply = self.rest.get(f"{self.endpoint}/{cidr_id}").validate().json()
            return model_validate(AllowedCIDRData, reply)
        except NotFoundError as exc:
            raise CapellaNotFoundError("CIDR not found") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Allowed CIDR Get Error",
                exc,
            ) from exc

    def get_allowed_cidr(self, network: str) -> AllowedCIDRData | None:
        self.cidr = self.get_by_name(network)
        return self.cidr
