"""Capella project resource."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

from couchbase_connect.capella.exceptions import (
    CapellaAPIError,
    CapellaNotFoundError,
    UserNotConfiguredError,
)
from couchbase_connect.capella.models import CreateProjectRequest, IdResponse, ProjectData
from couchbase_connect.capella.utils import dump_model, model_validate, random_name

if TYPE_CHECKING:
    from couchbase_connect.capella.cluster import CapellaCluster, ClusterConfig
    from couchbase_connect.capella.organization import CapellaOrganization
    from couchbase_connect.capella.user import CapellaUser

logger = logging.getLogger(__name__)


class CapellaProject:
    def __init__(
        self,
        organization: "CapellaOrganization",
        project_name: Optional[str] = None,
        project_data: Optional[ProjectData] = None,
    ) -> None:
        self.organization = organization
        self.rest = organization.rest
        self.endpoint = f"{organization.endpoint}/{organization.organization.id}/projects"
        self._user: Optional["CapellaUser"] = None
        self._clusters_by_id: Dict[str, "CapellaCluster"] = {}
        self._clusters_by_name: Dict[str, "CapellaCluster"] = {}
        if project_data is not None:
            self.project = project_data
            self.project_name = project_data.name or project_name or ""
        else:
            self.project = None
            self.project_name = project_name or organization.capella.project_name or "default"

    @classmethod
    def get_instance(cls, organization: "CapellaOrganization") -> "CapellaProject":
        return organization.get_default_project()

    @property
    def project_data(self) -> Optional[ProjectData]:
        return self.project

    @property
    def id(self) -> str:
        if self.project is None or self.project.id is None:
            raise RuntimeError("Project not resolved")
        return self.project.id

    def resolve_project(self) -> None:
        try:
            self._user = self.organization.get_user()
        except UserNotConfiguredError as exc:
            raise RuntimeError(
                "Capella user not configured. Please set capella.user.email or capella.user.id."
            ) from exc
        self.get_project()
        logger.debug("Project ID: %s", self.project.id if self.project else None)

    def get_default_cluster(self) -> "CapellaCluster":
        from couchbase_connect.capella.cluster import CapellaCluster

        cluster = CapellaCluster(self)
        try:
            cluster.resolve_cluster()
            if cluster.cluster_data is not None:
                self.register_cluster(cluster)
        except CapellaNotFoundError as exc:
            logger.debug("Cluster not found: %s", exc)
        except CapellaAPIError as exc:
            capella = self.organization.capella
            label = (
                capella.database_id
                if capella.has_database_id()
                else capella.database_name
            )
            raise RuntimeError(f"Can not find cluster {label}") from exc
        return cluster

    def create_cluster(
        self,
        cluster_name: Optional[object] = None,
        cluster_config: Optional["ClusterConfig"] = None,
    ) -> "CapellaCluster":
        from couchbase_connect.capella.cluster import CapellaCluster, ClusterConfig

        if isinstance(cluster_name, ClusterConfig) and cluster_config is None:
            cluster_config = cluster_name
            cluster_name = None
        if cluster_config is None:
            raise ValueError("cluster_config is required")
        capella = self.organization.capella
        if cluster_name is None:
            cluster_name = (
                capella.database_name
                if capella.has_database_name()
                else random_name()
            )
        cluster_name = str(cluster_name)

        cached = self.find_cluster_by_name(cluster_name)
        if cached is not None:
            try:
                cached.create_cluster(cluster_name, cluster_config)
            except CapellaAPIError as exc:
                raise RuntimeError(f"Can not create cluster {cluster_name}") from exc
            return cached

        cluster = CapellaCluster(self)
        try:
            cluster.create_cluster(cluster_name, cluster_config)
        except CapellaAPIError as exc:
            raise RuntimeError(f"Can not create cluster {cluster_name}") from exc
        self.register_cluster(cluster)
        return cluster

    def add_cluster(self, cluster_name: str) -> "CapellaCluster":
        from couchbase_connect.capella.cluster import CapellaCluster

        cached = self.find_cluster_by_name(cluster_name)
        if cached is not None:
            return cached
        cluster = CapellaCluster(self)
        try:
            cluster.add_cluster(cluster_name)
        except (CapellaAPIError, CapellaNotFoundError) as exc:
            raise RuntimeError(f"Can not add cluster {cluster_name}") from exc
        return cluster

    def register_cluster(self, cluster: "CapellaCluster") -> None:
        data = cluster.cluster_data
        if data is not None and data.id and data.name:
            self._clusters_by_id[data.id] = cluster
            self._clusters_by_name[data.name] = cluster

    def find_cluster_by_id(self, cluster_id: str) -> Optional["CapellaCluster"]:
        return self._clusters_by_id.get(cluster_id)

    def find_cluster_by_name(self, name: str) -> Optional["CapellaCluster"]:
        return self._clusters_by_name.get(name)

    def list_projects(self) -> List[ProjectData]:
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
            return [model_validate(ProjectData, item) for item in items]
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Project List Error",
                exc,
            ) from exc

    def get_project(self, project_id: Optional[str] = None) -> ProjectData:
        if project_id is None:
            return self._resolve_or_create_project()

        if self.project is not None and self.project.id == project_id:
            return self.project
        cached = self.organization.find_project_by_id(project_id)
        if cached is not None and cached.project is not None and cached.project.id == project_id:
            return cached.project
        return self.organization.fetch_project(project_id)

    def _resolve_or_create_project(self) -> ProjectData:
        capella = self.organization.capella
        if capella.has_project_id():
            self.project = self.get_project(capella.project_id)  # type: ignore[arg-type]
            return self.project

        projects = self.get_by_email()
        for pd in projects:
            if self.project_name == pd.name:
                self.project = pd
                return self.project
        self.project = self.create_project()
        return self.project

    def create_project(self) -> ProjectData:
        if self._user is None:
            self._user = self.organization.get_user()
        parameters = CreateProjectRequest(
            name=self.project_name,
            description="Automatically Created Project",
        )
        try:
            reply = self.rest.post(self.endpoint, dump_model(parameters)).validate().json()
            id_response = model_validate(IdResponse, reply)
            self._user.set_project_ownership(id_response.id)
            self.project = self.get_project(id_response.id)
            self.organization.register_project(self)
            return self.project
        except CapellaNotFoundError as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Project Create Error",
                exc,
            ) from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Project Create Error",
                exc,
            ) from exc

    def get_project_by_name(self, name: str) -> None:
        if self.project is not None and name == self.project.name:
            return
        cached = self.organization.find_project_by_name(name)
        if cached is not None and cached.project is not None:
            self.project = cached.project
            return
        for pd in self.list_projects():
            if name == pd.name:
                self.project = pd
                self.organization.register_project(self)
                return
        raise CapellaNotFoundError(f"Project not found: {name}")

    def get_by_email(self) -> List[ProjectData]:
        if self._user is None:
            self._user = self.organization.get_user()
        result: List[ProjectData] = []
        for project_id in self._user.get_projects():
            result.append(self.get_project(project_id))
        return result
