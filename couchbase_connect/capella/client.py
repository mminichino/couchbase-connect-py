"""Couchbase Capella API client configuration."""

from __future__ import annotations

import logging
from typing import Mapping, Optional

from restfull.bearer_auth import BearerAuth
from restfull.restapi import RestAPI

logger = logging.getLogger(__name__)

CAPELLA_ORGANIZATION_NAME = "capella.organization.name"
CAPELLA_ORGANIZATION_ID = "capella.organization.id"
CAPELLA_PROJECT_NAME = "capella.project.name"
CAPELLA_PROJECT_ID = "capella.project.id"
CAPELLA_DATABASE_NAME = "capella.database.name"
CAPELLA_DATABASE_ID = "capella.database.id"
CAPELLA_COLUMNAR_NAME = "capella.columnar.name"
CAPELLA_COLUMNAR_ID = "capella.columnar.id"
CAPELLA_TOKEN = "capella.token"
CAPELLA_API_HOST = "capella.api.host"
CAPELLA_USER_EMAIL = "capella.user.email"
CAPELLA_USER_ID = "capella.user.id"

CAPELLA_DEFAULT_PROJECT_NAME = "default"
CAPELLA_DEFAULT_API_HOST = "cloudapi.cloud.couchbase.com"


class CouchbaseCapella:

    def __init__(
        self,
        token: str,
        api_host: str = CAPELLA_DEFAULT_API_HOST,
        organization_name: Optional[str] = None,
        organization_id: Optional[str] = None,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
        database_name: Optional[str] = None,
        database_id: Optional[str] = None,
        columnar_name: Optional[str] = None,
        columnar_id: Optional[str] = None,
        account_email: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> None:
        self.token = token
        self.api_host = api_host or CAPELLA_DEFAULT_API_HOST
        self.organization_name = organization_name
        self.organization_id = organization_id
        self.project_name = project_name or CAPELLA_DEFAULT_PROJECT_NAME
        self.project_id = project_id
        self.database_name = database_name
        self.database_id = database_id
        self.columnar_name = columnar_name
        self.columnar_id = columnar_id
        self.account_email = account_email
        self.account_id = account_id
        self.rest = RestAPI(
            BearerAuth(token),
            hostname=self.api_host,
            use_ssl=True,
            port=443,
        )
        logger.debug("Capella client configured for host %s", self.api_host)

    @classmethod
    def from_properties(cls, props: Mapping[str, str]) -> "CouchbaseCapella":
        token = props.get(CAPELLA_TOKEN)
        if not token:
            raise RuntimeError(
                f"please set property {CAPELLA_TOKEN} to provide the API v4 token"
            )
        return cls(
            token=token,
            api_host=props.get(CAPELLA_API_HOST, CAPELLA_DEFAULT_API_HOST),
            organization_name=props.get(CAPELLA_ORGANIZATION_NAME),
            organization_id=props.get(CAPELLA_ORGANIZATION_ID),
            project_name=props.get(CAPELLA_PROJECT_NAME, CAPELLA_DEFAULT_PROJECT_NAME),
            project_id=props.get(CAPELLA_PROJECT_ID),
            database_name=props.get(CAPELLA_DATABASE_NAME),
            database_id=props.get(CAPELLA_DATABASE_ID),
            columnar_name=props.get(CAPELLA_COLUMNAR_NAME),
            columnar_id=props.get(CAPELLA_COLUMNAR_ID),
            account_email=props.get(CAPELLA_USER_EMAIL),
            account_id=props.get(CAPELLA_USER_ID),
        )

    def has_account_id(self) -> bool:
        return self.account_id is not None

    def has_account_email(self) -> bool:
        return self.account_email is not None

    def has_organization_name(self) -> bool:
        return self.organization_name is not None

    def has_organization_id(self) -> bool:
        return self.organization_id is not None

    def has_project_name(self) -> bool:
        return self.project_name is not None

    def has_project_id(self) -> bool:
        return self.project_id is not None

    def has_database_name(self) -> bool:
        return self.database_name is not None

    def has_database_id(self) -> bool:
        return self.database_id is not None

    def has_columnar_name(self) -> bool:
        return self.columnar_name is not None

    def has_columnar_id(self) -> bool:
        return self.columnar_id is not None
