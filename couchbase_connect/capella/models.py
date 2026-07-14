"""Pydantic v2 models for Capella REST request/response payloads."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CapellaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class AvailabilityType(str, Enum):
    SINGLE_ZONE = "single"
    MULTI_ZONE = "multi"

    def __str__(self) -> str:
        return self.value


class CloudType(str, Enum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"

    def __str__(self) -> str:
        return self.value


class State(str, Enum):
    HEALTHY = "healthy"
    DEPLOYING = "deploying"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    FAILED = "deploymentFailed"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


class SupportPlanType(str, Enum):
    BASIC = "basic"
    DEVELOPER = "developer pro"
    ENTERPRISE = "enterprise"

    def __str__(self) -> str:
        return self.value


class TimeZoneType(str, Enum):
    US_EAST = "ET"
    US_WEST = "PT"
    EUROPE = "GMT"
    ASIA = "IST"

    def __str__(self) -> str:
        return self.value


class StateWaitOperation(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"

    def evaluate(self, value: bool) -> bool:
        if self is StateWaitOperation.EQUALS:
            return value
        return not value


class AuditData(CapellaModel):
    created_by: Optional[str] = Field(default=None, alias="createdBy")
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    modified_by: Optional[str] = Field(default=None, alias="modifiedBy")
    modified_at: Optional[str] = Field(default=None, alias="modifiedAt")
    version: Optional[int] = None


class OrganizationPreferences(CapellaModel):
    session_duration: int = Field(default=0, alias="sessionDuration")


class OrganizationData(CapellaModel):
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    preferences: Optional[OrganizationPreferences] = Field(default=None, alias="preferences")
    audit: Optional[AuditData] = None

    @property
    def session_duration(self) -> int:
        if self.preferences is None:
            return 0
        return self.preferences.session_duration


class ProjectData(CapellaModel):
    id: Optional[str] = None
    description: Optional[str] = None
    name: Optional[str] = None
    audit: Optional[AuditData] = None


class CloudProviderData(CapellaModel):
    type: Optional[str] = None
    region: Optional[str] = None
    cidr: Optional[str] = None


class CouchbaseServerData(CapellaModel):
    version: Optional[str] = None


class AvailabilityData(CapellaModel):
    type: Optional[str] = None


class SupportData(CapellaModel):
    plan: Optional[str] = None
    timezone: Optional[str] = Field(default=None, alias="timezone")


class ComputeData(CapellaModel):
    cpu: int = 0
    ram: int = 0


class DiskConfig(CapellaModel):
    type: Optional[str] = None
    storage: Optional[int] = None
    iops: Optional[int] = None
    auto_expansion: Optional[bool] = Field(default=None, alias="autoExpansion")

    @classmethod
    def aws(cls, storage: int) -> "DiskConfig":
        matrix = {
            99: 3000,
            199: 4370,
            299: 5740,
            399: 7110,
            499: 8480,
            599: 9850,
            699: 11220,
            799: 12590,
            899: 13960,
            999: 15330,
            16384: 16000,
        }
        for threshold, iops in matrix.items():
            if threshold >= storage:
                return cls(type="gp3", storage=storage, iops=iops)
        raise ValueError(f"Invalid storage value: {storage}")

    @classmethod
    def gcp(cls, storage: int) -> "DiskConfig":
        return cls(type="pd-ssd", storage=storage)

    @classmethod
    def azure(cls, storage: int) -> "DiskConfig":
        matrix = {
            64: "P6",
            128: "P10",
            256: "P15",
            512: "P20",
            1024: "P30",
            2048: "P40",
            4096: "P50",
            8192: "P60",
        }
        for threshold, disk_type in matrix.items():
            if threshold >= storage:
                return cls(type=disk_type, auto_expansion=True)
        raise ValueError(f"Invalid storage value: {storage}")

    @classmethod
    def azure_ultra(cls, storage: int) -> "DiskConfig":
        matrix = {
            64: 3000,
            128: 4000,
            256: 6000,
            512: 8000,
            1024: 16000,
            2048: 16000,
            3072: 16000,
            4096: 16000,
            5120: 16000,
            6144: 16000,
            7168: 16000,
            8192: 16000,
        }
        for threshold, iops in matrix.items():
            if threshold >= storage:
                return cls(type="Ultra", storage=threshold, iops=iops)
        raise ValueError(f"Invalid storage value: {storage}")

    @classmethod
    def for_cloud(cls, cloud_type: CloudType, storage: int) -> "DiskConfig":
        if cloud_type == CloudType.AWS:
            return cls.aws(storage)
        if cloud_type == CloudType.GCP:
            return cls.gcp(storage)
        if cloud_type == CloudType.AZURE:
            return cls.azure(storage)
        raise ValueError(f"Unsupported cloud type: {cloud_type}")


class NodeConfig(CapellaModel):
    compute: Optional[ComputeData] = None
    disk: Optional[DiskConfig] = None


class ServiceGroupRequest(CapellaModel):
    num_of_nodes: int = Field(alias="numOfNodes")
    services: List[str]
    node: NodeConfig


class ServiceGroupData(CapellaModel):
    num_of_nodes: int = Field(default=0, alias="numOfNodes")
    services: Optional[List[str]] = None
    node: Optional[NodeConfig] = None

    @property
    def cpu(self) -> int:
        if self.node and self.node.compute:
            return self.node.compute.cpu
        return 0

    @property
    def ram(self) -> int:
        if self.node and self.node.compute:
            return self.node.compute.ram
        return 0

    @property
    def storage(self) -> int:
        if self.node and self.node.disk and self.node.disk.storage is not None:
            return self.node.disk.storage
        return 0

    @property
    def disk_type(self) -> Optional[str]:
        if self.node and self.node.disk:
            return self.node.disk.type
        return None

    @property
    def iops(self) -> int:
        if self.node and self.node.disk and self.node.disk.iops is not None:
            return self.node.disk.iops
        return 0


class CreateClusterRequest(CapellaModel):
    name: str
    description: Optional[str] = None
    cloud_provider: CloudProviderData = Field(alias="cloudProvider")
    couchbase_server: Optional[CouchbaseServerData] = Field(default=None, alias="couchbaseServer")
    service_groups: List[ServiceGroupRequest] = Field(alias="serviceGroups")
    availability: AvailabilityData
    support: SupportData


class CreateBucketRequest(CapellaModel):
    name: str
    type: str = "couchbase"
    storage_backend: str = Field(default="couchstore", alias="storageBackend")
    memory_allocation_in_mb: int = Field(default=128, alias="memoryAllocationInMb")
    bucket_conflict_resolution: str = Field(default="seqno", alias="bucketConflictResolution")
    durability_level: str = Field(default="none", alias="durabilityLevel")
    replicas: int = 1
    flush: bool = False
    time_to_live_in_seconds: int = Field(default=0, alias="timeToLiveInSeconds")


class CreateProjectRequest(CapellaModel):
    name: str
    description: Optional[str] = None


class CreateAllowedCidrRequest(CapellaModel):
    cidr: str
    comment: Optional[str] = None


class BucketStatsData(CapellaModel):
    item_count: int = Field(default=0, alias="itemCount")
    ops_per_second: int = Field(default=0, alias="opsPerSecond")
    disk_used_in_mib: int = Field(default=0, alias="diskUsedInMib")
    memory_used_in_mib: int = Field(default=0, alias="memoryUsedInMib")


class CapellaBucketData(CapellaModel):
    """Capella bucket document (named to avoid clash with Server BucketData)."""

    id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    storage_backend: Optional[str] = Field(default=None, alias="storageBackend")
    memory_allocation_in_mb: Optional[int] = Field(default=None, alias="memoryAllocationInMb")
    bucket_conflict_resolution: Optional[str] = Field(default=None, alias="bucketConflictResolution")
    durability_level: Optional[str] = Field(default=None, alias="durabilityLevel")
    replicas: Optional[int] = None
    flush: Optional[bool] = None
    flush_enabled: Optional[bool] = Field(default=None, alias="flushEnabled")
    time_to_live_in_seconds: Optional[int] = Field(default=None, alias="timeToLiveInSeconds")
    eviction_policy: Optional[str] = Field(default=None, alias="evictionPolicy")
    stats: Optional[BucketStatsData] = None
    priority: Optional[int] = None

    @property
    def item_count(self) -> int:
        return self.stats.item_count if self.stats else 0

    @property
    def ops_per_second(self) -> int:
        return self.stats.ops_per_second if self.stats else 0

    @property
    def disk_used_in_mib(self) -> int:
        return self.stats.disk_used_in_mib if self.stats else 0

    @property
    def memory_used_in_mib(self) -> int:
        return self.stats.memory_used_in_mib if self.stats else 0


class DatabaseResourceScopeData(CapellaModel):
    name: str
    collections: Optional[List[str]] = None


class DatabaseResourceBucketData(CapellaModel):
    name: str
    scopes: Optional[List[DatabaseResourceScopeData]] = None


class DatabaseResourceData(CapellaModel):
    buckets: Optional[List[DatabaseResourceBucketData]] = None


class DatabaseAccessEntry(CapellaModel):
    privileges: List[str]
    resources: DatabaseResourceData


class CredentialData(CapellaModel):
    id: Optional[str] = None
    name: Optional[str] = None
    access: Optional[List[DatabaseAccessEntry]] = None
    audit: Optional[AuditData] = None


class CreateDatabaseCredentialRequest(CapellaModel):
    name: str
    password: str
    access: List[DatabaseAccessEntry]


class CreateDatabaseCredentialResponse(CapellaModel):
    id: Optional[str] = None
    password: Optional[str] = None


class UpdateDatabaseCredentialRequest(CapellaModel):
    password: Optional[str] = None
    access: Optional[List[DatabaseAccessEntry]] = None


class AllowedCIDRData(CapellaModel):
    id: Optional[str] = None
    cidr: Optional[str] = None
    comment: Optional[str] = None
    expires_at: Optional[str] = Field(default=None, alias="expiresAt")
    status: Optional[str] = None
    type: Optional[str] = None
    audit: Optional[AuditData] = None


class CertificateResponse(CapellaModel):
    certificate: str


class IdResponse(CapellaModel):
    id: str


class ResourcesData(CapellaModel):
    type: Optional[str] = None
    id: Optional[str] = None
    roles: Optional[List[str]] = None


class CapellaOrgUserData(CapellaModel):
    """Organization user (from Java UserData)."""

    id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    inactive: bool = False
    organization_id: Optional[str] = Field(default=None, alias="organizationId")
    organization_roles: Optional[List[str]] = Field(default=None, alias="organizationRoles")
    last_login: Optional[str] = Field(default=None, alias="lastLogin")
    region: Optional[str] = None
    time_zone: Optional[str] = Field(default=None, alias="timeZone")
    enable_notifications: Optional[bool] = Field(default=None, alias="enableNotifications")
    expires_at: Optional[str] = Field(default=None, alias="expiresAt")
    resources: Optional[List[ResourcesData]] = None
    audit: Optional[AuditData] = None


class ClusterData(CapellaModel):
    id: Optional[str] = None
    app_service_id: Optional[str] = Field(default=None, alias="appServiceId")
    name: Optional[str] = None
    description: Optional[str] = None
    configuration_type: Optional[str] = Field(default=None, alias="configurationType")
    connection_string: Optional[str] = Field(default=None, alias="connectionString")
    cloud_provider: Optional[CloudProviderData] = Field(default=None, alias="cloudProvider")
    couchbase_server: Optional[CouchbaseServerData] = Field(default=None, alias="couchbaseServer")
    service_groups: Optional[List[ServiceGroupData]] = Field(default=None, alias="serviceGroups")
    availability: Optional[AvailabilityData] = None
    support: Optional[SupportData] = None
    current_state: Optional[str] = Field(default=None, alias="currentState")
    audit: Optional[AuditData] = None
    cmek_id: Optional[str] = Field(default=None, alias="cmekId")
    enable_private_dns_resolution: Optional[bool] = Field(
        default=None, alias="enablePrivateDNSResolution"
    )

    @property
    def version(self) -> Optional[str]:
        return self.couchbase_server.version if self.couchbase_server else None

    @property
    def availability_type(self) -> Optional[str]:
        return self.availability.type if self.availability else None
