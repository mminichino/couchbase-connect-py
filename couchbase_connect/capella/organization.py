"""Capella organization resource."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

from restfull.exceptions import NotFoundError

from couchbase_connect.capella.exceptions import CapellaAPIError, CapellaNotFoundError
from couchbase_connect.capella.models import OrganizationData, ProjectData
from couchbase_connect.capella.utils import model_validate

if TYPE_CHECKING:
    from couchbase_connect.capella.client import CouchbaseCapella
    from couchbase_connect.capella.project import CapellaProject
    from couchbase_connect.capella.user import CapellaUser

logger = logging.getLogger(__name__)

ENDPOINT = "/v4/organizations"


class CapellaOrganization:
    def __init__(self, capella: "CouchbaseCapella") -> None:
        self.capella = capella
        self.rest = capella.rest
        self.organization: Optional[OrganizationData] = None
        self._user: Optional["CapellaUser"] = None
        self._projects_by_id: Dict[str, "CapellaProject"] = {}
        self._projects_by_name: Dict[str, "CapellaProject"] = {}
        self.organization = self.get_default_org()
        logger.debug("Organization ID: %s", self.organization.id)

    @classmethod
    def get_instance(cls, capella: "CouchbaseCapella") -> "CapellaOrganization":
        return cls(capella)

    @property
    def endpoint(self) -> str:
        return ENDPOINT

    def get_user(self) -> "CapellaUser":
        from couchbase_connect.capella.user import CapellaUser

        if self._user is None:
            self._user = CapellaUser(self)

        try:
            assert self._user is not None
            return self._user
        except AssertionError:
            raise RuntimeError("Capella user not configured") from None

    def get_default_project(self) -> "CapellaProject":
        try:
            return self.get_project(self.capella.project_name or "default")
        except (CapellaAPIError, CapellaNotFoundError) as exc:
            raise RuntimeError(str(exc)) from exc

    def get_project(self, project_name: str) -> "CapellaProject":
        from couchbase_connect.capella.project import CapellaProject

        cached = self._projects_by_name.get(project_name)
        if cached is not None:
            return cached
        project = CapellaProject(self, project_name=project_name)
        project.resolve_project()
        self.register_project(project)
        return project

    def get_project_by_id(self, project_id: str) -> "CapellaProject":
        from couchbase_connect.capella.project import CapellaProject

        cached = self._projects_by_id.get(project_id)
        if cached is not None:
            return cached
        project_data = self.fetch_project(project_id)
        project = CapellaProject(self, project_data=project_data)
        self.register_project(project)
        return project

    def fetch_project(self, project_id: str) -> ProjectData:
        project_endpoint = f"{self.endpoint}/{self.organization.id}/projects/{project_id}"
        try:
            reply = self.rest.get(project_endpoint).validate().json()
            return model_validate(ProjectData, reply)
        except NotFoundError as exc:
            raise CapellaNotFoundError("Project ID not found") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Project Get Error",
                exc,
            ) from exc

    def register_project(self, project: "CapellaProject") -> None:
        if project.project_data is not None:
            self._projects_by_id[project.id] = project
            self._projects_by_name[project.project_name] = project

    def find_project_by_id(self, project_id: str) -> Optional["CapellaProject"]:
        return self._projects_by_id.get(project_id)

    def find_project_by_name(self, name: str) -> Optional["CapellaProject"]:
        return self._projects_by_name.get(name)

    def list(self) -> List[OrganizationData]:
        try:
            reply = self.rest.get(ENDPOINT).validate().json("data")
            if not reply:
                return []
            return [model_validate(OrganizationData, item) for item in reply]
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Organization List Error",
                exc,
            ) from exc

    def get_by_id(self, org_id: str) -> OrganizationData:
        if self.organization is not None and self.organization.id == org_id:
            return self.organization
        org_endpoint = f"{ENDPOINT}/{org_id}"
        try:
            reply = self.rest.get(org_endpoint).validate().json()
            return model_validate(OrganizationData, reply)
        except NotFoundError as exc:
            raise CapellaNotFoundError("Organization ID not found") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Organization Get Error",
                exc,
            ) from exc

    def get_by_name(self, organization_name: str) -> OrganizationData:
        if self.organization is not None and organization_name == self.organization.name:
            return self.organization
        for org in self.list():
            if organization_name == org.name:
                return org
        raise CapellaNotFoundError(f"Can not find organization {organization_name}")

    def get_default_org(self) -> OrganizationData:
        try:
            if self.capella.has_organization_id():
                return self.get_by_id(self.capella.organization_id)  # type: ignore[arg-type]
            if self.capella.has_organization_name():
                return self.get_by_name(self.capella.organization_name)  # type: ignore[arg-type]
            orgs = self.list()
            return orgs[0]
        except (CapellaNotFoundError, CapellaAPIError, IndexError) as exc:
            raise RuntimeError("Can not find the Capella Organization") from exc
