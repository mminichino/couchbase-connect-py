"""Capella database credentials resource."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional, Sequence

from restfull.exceptions import NotFoundError

from couchbase_connect.capella.exceptions import CapellaAPIError, CapellaNotFoundError
from couchbase_connect.capella.models import (
    CreateDatabaseCredentialRequest,
    CreateDatabaseCredentialResponse,
    CredentialData,
    DatabaseAccessEntry,
    DatabaseResourceBucketData,
    DatabaseResourceData,
    UpdateDatabaseCredentialRequest,
)
from couchbase_connect.capella.utils import dump_model, model_validate

if TYPE_CHECKING:
    from couchbase_connect.capella.cluster import CapellaCluster

logger = logging.getLogger(__name__)


def _default_access() -> List[DatabaseAccessEntry]:
    return [
        DatabaseAccessEntry(
            privileges=["data_reader", "data_writer"],
            resources=DatabaseResourceData(
                buckets=[DatabaseResourceBucketData(name="*", scopes=None)]
            ),
        )
    ]


class CapellaCredentials:
    def __init__(self, cluster: "CapellaCluster") -> None:
        if cluster.cluster_data is None or cluster.cluster_data.id is None:
            raise RuntimeError("Cluster must be resolved before accessing credentials")
        self.cluster = cluster
        self.rest = cluster.rest
        self.endpoint = f"{cluster.endpoint}/{cluster.cluster_data.id}/users"
        self.user: Optional[CredentialData] = None
        self.username: Optional[str] = None
        self.password: Optional[str] = None

    @classmethod
    def get_instance(
        cls,
        cluster: "CapellaCluster",
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> "CapellaCredentials":
        credentials = cluster.get_credentials()
        if credentials is None:
            credentials = cls(cluster)
            cluster.credentials = credentials
        if username is not None and password is not None:
            try:
                credentials.add_credentials(username, password)
            except (CapellaAPIError, CapellaNotFoundError) as exc:
                raise RuntimeError(f"Can not add credentials {username}") from exc
        return credentials

    def is_user(self, username: str) -> Optional[CredentialData]:
        for listed in self.list():
            if username == listed.name:
                return listed
        return None

    def create_credential(
        self,
        username: str,
        password: str,
        access: Optional[Sequence[DatabaseAccessEntry]] = None,
    ) -> CreateDatabaseCredentialResponse:
        self.username = username
        self.password = password
        check = self.is_user(username)
        if check is not None:
            logger.debug("User %s already exists", username)
            self.user = check
            return CreateDatabaseCredentialResponse(id=check.id, password=None)

        logger.debug("Creating database credential %s", username)
        effective = list(access) if access else _default_access()
        parameters = CreateDatabaseCredentialRequest(
            name=username,
            password=password,
            access=effective,
        )
        try:
            reply = self.rest.post(self.endpoint, dump_model(parameters)).validate().json()
            response = model_validate(CreateDatabaseCredentialResponse, reply)
            try:
                self.user = self.get_by_id(response.id)  # type: ignore[arg-type]
            except CapellaNotFoundError as exc:
                raise RuntimeError("Database credential creation failed") from exc
            return response
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Credentials Create Error",
                exc,
            ) from exc

    def add_credentials(self, username: str, password: str) -> CredentialData:
        self.username = username
        self.password = password
        self.user = self.get_by_name(username)
        logger.debug("Added existing database credential %s", username)
        return self.user

    def update_credential(
        self, user_id: str, request: UpdateDatabaseCredentialRequest
    ) -> None:
        try:
            self.rest.put(f"{self.endpoint}/{user_id}", dump_model(request)).validate()
            self.user = self.get_by_id(user_id)
        except CapellaNotFoundError as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Credentials not found",
                exc,
            ) from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Credentials Update Error",
                exc,
            ) from exc

    def delete(self) -> None:
        if self.user is None or self.user.id is None:
            return
        try:
            self.rest.delete(f"{self.endpoint}/{self.user.id}").validate()
            logger.debug("User %s deleted", self.user.name)
            self.user = None
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Credentials Delete Error",
                exc,
            ) from exc

    def list(self) -> List[CredentialData]:
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
            return [model_validate(CredentialData, item) for item in items]
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Credentials List Error",
                exc,
            ) from exc

    def get_by_name(self, username: str) -> CredentialData:
        if self.user is not None and username == self.user.name:
            return self.user
        for listed in self.list():
            if username == listed.name:
                return listed
        raise CapellaNotFoundError(f"Can not find user {username}")

    def get_by_id(self, user_id: str) -> CredentialData:
        if self.user is not None and self.user.id == user_id:
            return self.user
        try:
            reply = self.rest.get(f"{self.endpoint}/{user_id}").validate().json()
            return model_validate(CredentialData, reply)
        except NotFoundError as exc:
            raise CapellaNotFoundError("Database credential not found") from exc
        except Exception as exc:
            raise CapellaAPIError(
                self.rest.response_code,
                self.rest.response_text,
                "Credentials Get Error",
                exc,
            ) from exc

    def get_credential(self, username: str) -> CredentialData:
        self.user = self.get_by_name(username)
        return self.user

    def get_username(self) -> Optional[str]:
        return self.username

    def get_password(self) -> Optional[str]:
        return self.password
