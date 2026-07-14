"""Capella bucket resource."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Mapping, Optional

from restfull.exceptions import NotFoundError

from couchbase_connect.capella.exceptions import CapellaAPIError, CapellaNotFoundError
from couchbase_connect.capella.models import CapellaBucketData, CreateBucketRequest
from couchbase_connect.capella.utils import dump_model, model_validate

if TYPE_CHECKING:
    from couchbase_connect.capella.cluster import CapellaCluster

logger = logging.getLogger(__name__)


class CapellaBucket:
    def __init__(self, cluster: "CapellaCluster") -> None:
        if cluster.cluster_data is None or cluster.cluster_data.id is None:
            raise RuntimeError("Cluster must be resolved before accessing buckets")
        self.cluster = cluster
        self.rest = cluster.rest
        self.endpoint = f"{cluster.endpoint}/{cluster.cluster_data.id}/buckets"
        self.bucket: Optional[CapellaBucketData] = None

    @classmethod
    def get_instance(
        cls,
        cluster: "CapellaCluster",
        bucket_name: Optional[str] = None,
    ) -> "CapellaBucket":
        bucket_service = cluster.get_bucket()
        if bucket_service is None:
            bucket_service = cls(cluster)
            cluster.bucket = bucket_service
        if bucket_name is not None:
            bucket_service.get_bucket(bucket_name)
        return bucket_service

    @property
    def bucket_data(self) -> Optional[CapellaBucketData]:
        return self.bucket

    def is_bucket(self, name: str) -> Optional[CapellaBucketData]:
        for listed in self.list():
            if name == listed.name:
                return listed
        return None

    def create_bucket(self, settings: Mapping[str, Any]) -> CapellaBucketData:
        """Create a bucket from a settings dict (skip if name already exists)."""
        name = settings.get("name")
        if not name:
            raise ValueError("settings must include 'name'")
        check = self.is_bucket(str(name))
        if check is not None:
            logger.debug("Bucket %s already exists", name)
            self.bucket = check
            return check

        parameters = CreateBucketRequest(
            name=str(name),
            type=str(settings.get("type", settings.get("bucketType", "couchbase"))),
            storageBackend=str(
                settings.get(
                    "storageBackend",
                    settings.get("storage_backend", "couchstore"),
                )
            ),
            memoryAllocationInMb=int(
                settings.get(
                    "memoryAllocationInMb",
                    settings.get("memory_allocation_in_mb", settings.get("ramQuotaMB", 128)),
                )
            ),
            bucketConflictResolution=str(
                settings.get(
                    "bucketConflictResolution",
                    settings.get("bucket_conflict_resolution", "seqno"),
                )
            ),
            durabilityLevel=str(
                settings.get(
                    "durabilityLevel",
                    settings.get("durability_level", "none"),
                )
            ).lower(),
            replicas=int(
                settings.get("replicas", settings.get("numReplicas", settings.get("num_replicas", 1)))
            ),
            flush=bool(
                settings.get("flush", settings.get("flushEnabled", settings.get("flush_enabled", False)))
            ),
            timeToLiveInSeconds=int(
                settings.get(
                    "timeToLiveInSeconds",
                    settings.get("time_to_live_in_seconds", settings.get("maxExpiry", 0)),
                )
            ),
        )
        logger.debug("Creating bucket with settings %s", dump_model(parameters))
        try:
            reply = self.rest.post(self.endpoint, dump_model(parameters)).validate().json()
            bucket_id = reply.get("id")
            try:
                self.bucket = self.get_by_id(bucket_id)
            except CapellaNotFoundError as exc:
                raise RuntimeError("Bucket creation failed") from exc
            return self.bucket
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Bucket Create Error",
                exc,
            ) from exc

    def delete(self) -> None:
        if self.bucket is None or self.bucket.id is None:
            return
        try:
            self.rest.delete(f"{self.endpoint}/{self.bucket.id}").validate()
            logger.debug("Bucket %s deleted", self.bucket.name)
            self.bucket = None
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Bucket Delete Error",
                exc,
            ) from exc

    def list(self) -> List[CapellaBucketData]:
        try:
            reply = self.rest.get(self.endpoint).validate().json("data")
            if not reply:
                return []
            return [model_validate(CapellaBucketData, item) for item in reply]
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Bucket List Error",
                exc,
            ) from exc

    def get_by_name(self, bucket_name: str) -> CapellaBucketData:
        if self.bucket is not None and bucket_name == self.bucket.name:
            return self.bucket
        for listed in self.list():
            if bucket_name == listed.name:
                return listed
        raise CapellaNotFoundError(f"Can not find bucket {bucket_name}")

    def get_by_id(self, bucket_id: str) -> CapellaBucketData:
        if self.bucket is not None and self.bucket.id == bucket_id:
            return self.bucket
        try:
            reply = self.rest.get(f"{self.endpoint}/{bucket_id}").validate().json()
            return model_validate(CapellaBucketData, reply)
        except NotFoundError as exc:
            raise CapellaNotFoundError("Bucket not found") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Bucket Get Error",
                exc,
            ) from exc

    def get_bucket(self, bucket_name: str) -> CapellaBucketData:
        self.bucket = self.get_by_name(bucket_name)
        return self.bucket
