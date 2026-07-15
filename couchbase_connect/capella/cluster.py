"""Capella cluster resource and config builders."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Sequence

from restfull.exceptions import NotFoundError

from couchbase_connect.capella.exceptions import CapellaAPIError, CapellaNotFoundError
from couchbase_connect.capella.models import (
    AvailabilityData,
    AvailabilityType,
    CloudProviderData,
    CloudType,
    ClusterData,
    ComputeData,
    CouchbaseServerData,
    CreateClusterRequest,
    DiskConfig,
    NodeConfig,
    ServiceGroupRequest,
    State,
    StateWaitOperation,
    SupportData,
    SupportPlanType,
    TimeZoneType,
)
from couchbase_connect.capella.utils import dump_model, model_validate

if TYPE_CHECKING:
    from couchbase_connect.capella.allowed_cidr import CapellaAllowedCIDR
    from couchbase_connect.capella.bucket import CapellaBucket
    from couchbase_connect.capella.certificate import CapellaCertificate
    from couchbase_connect.capella.credentials import CapellaCredentials
    from couchbase_connect.capella.project import CapellaProject

logger = logging.getLogger(__name__)


@dataclass
class ServiceGroupConfig:
    cpu: int = 4
    ram: int = 16
    storage: int = 256
    num_of_nodes: int = 3
    services: List[str] = field(
        default_factory=lambda: ["data", "query", "index", "search"]
    )

    def set_cpu(self, value: int) -> "ServiceGroupConfig":
        self.cpu = value
        return self

    def set_ram(self, value: int) -> "ServiceGroupConfig":
        self.ram = value
        return self

    def set_storage(self, value: int) -> "ServiceGroupConfig":
        self.storage = value
        return self

    def set_num_of_nodes(self, value: int) -> "ServiceGroupConfig":
        self.num_of_nodes = value
        return self

    def set_services(self, services: Sequence[str]) -> "ServiceGroupConfig":
        self.services = list(services)
        return self

    # Java-style fluent names (same as property names via methods for chaining).
    def with_cpu(self, value: int) -> "ServiceGroupConfig":
        return self.set_cpu(value)

    def with_ram(self, value: int) -> "ServiceGroupConfig":
        return self.set_ram(value)

    def with_storage(self, value: int) -> "ServiceGroupConfig":
        return self.set_storage(value)

    def with_num_of_nodes(self, value: int) -> "ServiceGroupConfig":
        return self.set_num_of_nodes(value)

    def with_services(self, services: Sequence[str]) -> "ServiceGroupConfig":
        return self.set_services(services)

    def to_request(self, cloud_type: CloudType) -> ServiceGroupRequest:
        return ServiceGroupRequest(
            numOfNodes=self.num_of_nodes,
            services=list(self.services),
            node=NodeConfig(
                compute=ComputeData(cpu=self.cpu, ram=self.ram),
                disk=DiskConfig.for_cloud(cloud_type, self.storage),
            ),
        )


@dataclass
class ClusterConfig:
    description: str = "Automation Managed Cluster"
    cloud_type: CloudType = CloudType.AWS
    cloud_region: str = ""
    cidr: Optional[str] = None
    version: Optional[str] = None
    availability_type: AvailabilityType = AvailabilityType.MULTI_ZONE
    support_plan: SupportPlanType = SupportPlanType.DEVELOPER
    time_zone: TimeZoneType = TimeZoneType.US_WEST
    service_groups: List[ServiceGroupConfig] = field(default_factory=list)

    def with_description(self, description: str) -> "ClusterConfig":
        self.description = description
        return self

    def with_cloud_type(self, cloud_type: CloudType) -> "ClusterConfig":
        self.cloud_type = cloud_type
        return self

    def with_cloud_region(self, cloud_region: str) -> "ClusterConfig":
        self.cloud_region = cloud_region
        return self

    def with_cidr(self, cidr: str) -> "ClusterConfig":
        self.cidr = cidr
        return self

    def with_version(self, version: str) -> "ClusterConfig":
        self.version = version
        return self

    def availability(self, availability: AvailabilityType) -> "ClusterConfig":
        self.availability_type = availability
        return self

    def with_support_plan(self, support_plan: SupportPlanType) -> "ClusterConfig":
        self.support_plan = support_plan
        return self

    def with_time_zone(self, time_zone: TimeZoneType) -> "ClusterConfig":
        self.time_zone = time_zone
        return self

    def with_service_groups(self, service_groups: List[ServiceGroupConfig]) -> "ClusterConfig":
        self.service_groups = service_groups
        return self

    def add_service_group(self, service_group: ServiceGroupConfig) -> "ClusterConfig":
        self.service_groups.append(service_group)
        return self

    def single_node(self, services: Optional[Sequence[str]] = None) -> "ClusterConfig":
        self.availability_type = AvailabilityType.SINGLE_ZONE
        group = ServiceGroupConfig().with_num_of_nodes(1).with_storage(100)
        if services is not None:
            group.with_services(services)
        return self.add_service_group(group)

    def create(self, cluster_name: str) -> CreateClusterRequest:
        if not self.service_groups:
            self.add_service_group(ServiceGroupConfig())
        if not self.cloud_region:
            if self.cloud_type == CloudType.GCP:
                self.cloud_region = "us-east4"
            elif self.cloud_type == CloudType.AZURE:
                self.cloud_region = "eastus"
            else:
                self.cloud_region = "us-east-2"
        groups = [sg.to_request(self.cloud_type) for sg in self.service_groups]
        server = CouchbaseServerData(version=self.version) if self.version else None
        return CreateClusterRequest(
            name=cluster_name,
            description=self.description,
            cloudProvider=CloudProviderData(
                type=str(self.cloud_type),
                region=self.cloud_region,
                cidr=self.cidr,
            ),
            couchbaseServer=server,
            serviceGroups=groups,
            availability=AvailabilityData(type=str(self.availability_type)),
            support=SupportData(
                plan=str(self.support_plan),
                timezone=str(self.time_zone),
            ),
        )


class CapellaCluster:
    def __init__(self, project: "CapellaProject") -> None:
        self.project = project
        self.rest = project.organization.capella.rest
        self.endpoint = f"{project.endpoint}/{project.id}/clusters"
        self.cluster: Optional[ClusterData] = None
        self.bucket: Optional["CapellaBucket"] = None
        self.credentials: Optional["CapellaCredentials"] = None
        self.allowed_cidr: Optional["CapellaAllowedCIDR"] = None
        self.certificate: Optional["CapellaCertificate"] = None

    @classmethod
    def get_instance(
        cls,
        project: "CapellaProject",
        cluster_name: Optional[str] = None,
        cluster_config: Optional[ClusterConfig] = None,
    ) -> "CapellaCluster":
        if cluster_name is not None and cluster_config is not None:
            return project.create_cluster(cluster_name, cluster_config)
        if cluster_config is not None:
            return project.create_cluster(cluster_config=cluster_config)
        if cluster_name is not None:
            return project.add_cluster(cluster_name)
        return project.get_default_cluster()

    @property
    def cluster_data(self) -> Optional[ClusterData]:
        return self.cluster

    def resolve_cluster(self) -> None:
        capella = self.project.organization.capella
        if capella.has_database_id():
            self.cluster = self.get_by_id(capella.database_id)  # type: ignore[arg-type]
        elif capella.has_database_name():
            self.cluster = self.get_by_name(capella.database_name)  # type: ignore[arg-type]
        self._attach_cluster_services()

    def add_cluster(self, cluster_name: str) -> None:
        self.cluster = self.get_by_name(cluster_name)
        self._attach_cluster_services()
        self._populate_certificate()
        self.project.register_cluster(self)

    def wait(
        self,
        cluster_id: str,
        state: State,
        operation: StateWaitOperation,
    ) -> State:
        cluster_endpoint = f"{self.endpoint}/{cluster_id}"
        wait_for_destroyed = (
            operation is StateWaitOperation.NOT_EQUALS and state is State.DESTROYING
        )
        for _ in range(600):
            try:
                reply = self.rest.get(cluster_endpoint).validate().json()
                current_state = reply.get("currentState")
                if current_state == str(State.FAILED):
                    return State.FAILED
                if wait_for_destroyed:
                    time.sleep(1)
                    continue
                check = operation.evaluate(current_state == str(state))
                if not check:
                    time.sleep(1)
                    continue
                return State.HEALTHY
            except NotFoundError:
                logger.debug("Cluster not found")
                return State.DESTROYED
            except Exception as exc:
                raise CapellaAPIError(
                    self.rest.response_code,
                    self.rest.response_text,
                    "Cluster Wait Error",
                    exc,
                ) from exc
        return State.UNKNOWN

    def is_cluster(self, name: str) -> Optional[ClusterData]:
        for listed in self.list():
            if name == listed.name:
                return listed
        return None

    def create_cluster(self, cluster_name: str, cluster_config: ClusterConfig) -> None:
        check = self.is_cluster(cluster_name)
        if check is not None:
            logger.debug("Cluster %s already exists", cluster_name)
            wait_result = self.wait(check.id, State.HEALTHY, StateWaitOperation.EQUALS)  # type: ignore[arg-type]
            if wait_result is not State.HEALTHY:
                logger.debug("Existing Cluster %s reached state %s", check.id, wait_result)
                raise RuntimeError(f"Cluster is not healthy: {wait_result}")
            try:
                self.cluster = self.get_by_id(check.id)  # type: ignore[arg-type]
            except CapellaNotFoundError as exc:
                raise RuntimeError("Cluster lookup failed") from exc
            self._attach_cluster_services()
            self._populate_certificate()
            self.project.register_cluster(self)
            return

        parameters = cluster_config.create(cluster_name)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                reply = (
                    self.rest.post(self.endpoint, dump_model(parameters)).validate().json()
                )
                cluster_id = reply.get("id")
                logger.debug(
                    "Waiting for cluster %s to be healthy (attempt %s)",
                    cluster_id,
                    attempt,
                )
                wait_result = self.wait(
                    cluster_id, State.HEALTHY, StateWaitOperation.EQUALS
                )
                if wait_result is State.HEALTHY:
                    try:
                        self.cluster = self.get_by_id(cluster_id)
                    except CapellaNotFoundError as exc:
                        raise RuntimeError("Cluster creation failed") from exc
                    self._attach_cluster_services()
                    self._populate_certificate()
                    self.project.register_cluster(self)
                    return
                if wait_result is State.FAILED:
                    logger.debug(
                        "Cluster %s deployment failed (attempt %s)", cluster_id, attempt
                    )
                    self._delete_cluster_by_id(cluster_id)
                    if attempt < max_attempts:
                        continue
                    raise RuntimeError(
                        f"Cluster creation failed after {max_attempts} attempts"
                    )
                logger.debug(
                    "Cluster %s reached state %s (attempt %s)",
                    cluster_id,
                    wait_result,
                    attempt,
                )
                raise RuntimeError(f"Cluster creation failed: {wait_result}")
            except CapellaAPIError:
                raise
            except Exception as exc:
                raise CapellaAPIError(
                    self.rest.response_code,
                    self.rest.response_text,
                    "Cluster Create Error",
                    exc,
                ) from exc

    def _delete_cluster_by_id(self, cluster_id: str) -> None:
        try:
            self.rest.delete(f"{self.endpoint}/{cluster_id}").validate()
            logger.debug("Waiting for cluster %s to be deleted", cluster_id)
            wait_result = self.wait(
                cluster_id, State.DESTROYING, StateWaitOperation.NOT_EQUALS
            )
            if wait_result is not State.DESTROYED:
                logger.debug(
                    "Cluster %s deletion reached state %s", cluster_id, wait_result
                )
        except NotFoundError:
            logger.debug("Cluster %s already deleted", cluster_id)
        except Exception as exc:
            logger.debug("Failed to delete cluster %s: %s", cluster_id, exc)

    def _attach_cluster_services(self) -> None:
        from couchbase_connect.capella.allowed_cidr import CapellaAllowedCIDR
        from couchbase_connect.capella.bucket import CapellaBucket
        from couchbase_connect.capella.certificate import CapellaCertificate
        from couchbase_connect.capella.credentials import CapellaCredentials

        if self.cluster is None or self.cluster.id is None:
            return
        self.bucket = CapellaBucket(self)
        self.credentials = CapellaCredentials(self)
        self.allowed_cidr = CapellaAllowedCIDR(self)
        self.certificate = CapellaCertificate(self)

    def _populate_certificate(self) -> None:
        if self.certificate is None:
            return
        try:
            pem = self.certificate.get_cluster_certificate()
            self.certificate.set_certificate(pem)
        except CapellaAPIError as exc:
            logger.debug("Unable to fetch cluster certificate: %s", exc)

    def delete(self) -> None:
        if self.cluster is None or self.cluster.id is None:
            return
        try:
            cluster_id = self.cluster.id
            cluster_name = self.cluster.name
            self.rest.delete(f"{self.endpoint}/{cluster_id}").validate()
            logger.debug("Waiting for cluster %s to be deleted", cluster_name)
            wait_result = self.wait(
                cluster_id, State.DESTROYING, StateWaitOperation.NOT_EQUALS
            )
            if wait_result is not State.DESTROYED:
                logger.debug(
                    "Cluster %s deletion reached state %s", cluster_name, wait_result
                )
                raise RuntimeError(f"Cluster deletion failed: {wait_result}")
            self.cluster = None
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Cluster Delete Error",
                exc,
            ) from exc

    def list(self) -> List[ClusterData]:
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
            return [model_validate(ClusterData, item) for item in items]
        except NotFoundError:
            logger.debug("Project does not have any clusters")
            return []
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Cluster List Error",
                exc,
            ) from exc

    def get_by_name(self, cluster_name: str) -> ClusterData:
        if self.cluster is not None and cluster_name == self.cluster.name:
            return self.cluster
        cached = self.project.find_cluster_by_name(cluster_name)
        if (
            cached is not None
            and cached.cluster is not None
            and cluster_name == cached.cluster.name
        ):
            return cached.cluster
        for listed in self.list():
            if cluster_name == listed.name:
                return listed
        raise CapellaNotFoundError(f"Can not find cluster {cluster_name}")

    def get_by_id(self, cluster_id: str) -> ClusterData:
        if self.cluster is not None and self.cluster.id == cluster_id:
            return self.cluster
        cached = self.project.find_cluster_by_id(cluster_id)
        if (
            cached is not None
            and cached.cluster is not None
            and cached.cluster.id == cluster_id
        ):
            return cached.cluster
        cluster_endpoint = f"{self.endpoint}/{cluster_id}"
        try:
            reply = self.rest.get(cluster_endpoint).validate().json()
            return model_validate(ClusterData, reply)
        except NotFoundError as exc:
            raise CapellaNotFoundError("Cluster ID not found") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Cluster Get Error",
                exc,
            ) from exc

    def get_cluster(self, cluster_name: Optional[str] = None) -> None:
        capella = self.project.organization.capella
        if cluster_name is not None:
            self.cluster = self.get_by_name(cluster_name)
        elif capella.has_database_id():
            self.cluster = self.get_by_id(capella.database_id)  # type: ignore[arg-type]
        elif capella.has_database_name():
            self.cluster = self.get_by_name(capella.database_name)  # type: ignore[arg-type]
        self.project.register_cluster(self)

    def get_connect_string(self) -> Optional[str]:
        if self.cluster is None or self.cluster.id is None:
            return None
        try:
            self.cluster = self.get_by_id(self.cluster.id)
        except (CapellaNotFoundError, CapellaAPIError) as exc:
            logger.debug("Unable to refresh cluster connection string: %s", exc)
        if self.cluster is None or not self.cluster.connection_string:
            return None
        from couchbase_connect.capella.connect import normalize_connect_string

        return normalize_connect_string(self.cluster.connection_string)

    def get_bucket(self) -> Optional["CapellaBucket"]:
        return self.bucket

    def get_credentials(self) -> Optional["CapellaCredentials"]:
        return self.credentials

    def get_allowed_cidr(self) -> Optional["CapellaAllowedCIDR"]:
        return self.allowed_cidr

    def get_certificate(self) -> Optional["CapellaCertificate"]:
        return self.certificate
