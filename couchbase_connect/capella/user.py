"""Capella organization user resource."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional, Set

from restfull.exceptions import NotFoundError

from couchbase_connect.capella.exceptions import (
    CapellaAPIError,
    CapellaNotFoundError,
    UserNotConfiguredError,
)
from couchbase_connect.capella.models import CapellaOrgUserData
from couchbase_connect.capella.utils import model_validate

if TYPE_CHECKING:
    from couchbase_connect.capella.organization import CapellaOrganization

logger = logging.getLogger(__name__)


class CapellaUser:
    def __init__(self, organization: "CapellaOrganization") -> None:
        self.organization = organization
        self.rest = organization.rest
        self.endpoint = f"{organization.endpoint}/{organization.organization.id}/users"
        self.email: Optional[str] = None
        self.user: Optional[CapellaOrgUserData] = None

        capella = organization.capella
        try:
            if capella.has_account_email():
                self.email = capella.account_email
                self.user = self.get_by_email(self.email)  # type: ignore[arg-type]
            elif capella.has_account_id():
                self.user = self.get_by_id(capella.account_id)  # type: ignore[arg-type]
                self.email = self.user.email
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        if self.user is None or self.email is None:
            raise UserNotConfiguredError("Capella user not configured")
        logger.debug("User ID: %s (%s)", self.user.id, self.user.email)

    @classmethod
    def get_instance(cls, organization: "CapellaOrganization") -> "CapellaUser":
        return organization.get_user()

    def list_users(self) -> List[CapellaOrgUserData]:
        try:
            items = (
                self.rest.get_paged(
                    self.endpoint,
                    "page",
                    "totalItems",
                    "last",
                    "perPage",
                    100,
                    "data",
                    "cursor",
                    "pages",
                )
                .validate()
                .json_list()
                .as_list
            )
            return [model_validate(CapellaOrgUserData, item) for item in items]
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "User List Error",
                exc,
            ) from exc

    def get_unique_users(self) -> List[CapellaOrgUserData]:
        result = self.list_users()
        size = len(result)
        user_set: Set[str] = {u.id for u in result if u.id}
        users_by_id = {u.id: u for u in result if u.id}
        while len(user_set) < size:
            update = self.list_users()
            for user in update:
                if user.id and user.id not in users_by_id:
                    users_by_id[user.id] = user
                    user_set.add(user.id)
            size = len(users_by_id)
        return list(users_by_id.values())

    def get_by_id(self, user_id: str) -> CapellaOrgUserData:
        if self.user is not None and self.user.id == user_id:
            return self.user
        user_endpoint = f"{self.endpoint}/{user_id}"
        try:
            reply = self.rest.get(user_endpoint).validate().json()
            return model_validate(CapellaOrgUserData, reply)
        except NotFoundError as exc:
            raise CapellaNotFoundError("User ID not found") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "User Get Error",
                exc,
            ) from exc

    def get_by_email(self, email: Optional[str] = None) -> CapellaOrgUserData:
        target = email if email is not None else self.email
        if target is None:
            raise RuntimeError("No email configured")
        if self.user is not None and self.user.email == target:
            return self.user
        for listed in self.list_users():
            if listed.email == target:
                return listed
        raise RuntimeError(f"No user for email: {target}")

    def get_projects(self) -> List[str]:
        result: List[str] = []
        if self.user is None or self.user.resources is None:
            return result
        for resource in self.user.resources:
            if resource.type == "project" and resource.id:
                result.append(resource.id)
        return result

    def set_project_ownership(self, project_id: str) -> None:
        if self.user is None or self.user.id is None:
            raise CapellaAPIError(0, None, "User not resolved")
        user_endpoint = f"{self.endpoint}/{self.user.id}"
        payload = [
            {
                "op": "add",
                "path": f"/resources/{project_id}",
                "value": {
                    "type": "project",
                    "id": project_id,
                    "roles": ["projectOwner"],
                },
            }
        ]
        try:
            self.rest.patch(user_endpoint, payload).validate()
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "User Set Error",
                exc,
            ) from exc
