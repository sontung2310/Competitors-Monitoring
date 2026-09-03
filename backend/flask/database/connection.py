"""MongoDB client configuration and connection construction."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


class MongoConfigurationError(RuntimeError):
    """Raised when the application cannot construct a MongoDB connection."""


@dataclass(frozen=True)
class MongoSettings:
    """Runtime settings required to select a MongoDB database."""

    uri: str
    database_name: str

    @classmethod
    def from_env(
        cls,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "MongoSettings":
        values = environ if environ is not None else os.environ
        uri = values.get("MONGODB_URI")
        if not uri:
            raise MongoConfigurationError("MONGODB_URI is not configured")

        database_name = (
            values.get("MONGODB_DATABASE")
            or values.get("MONGODB_DB_NAME")
            or "competitor_monitoring"
        )
        return cls(uri=uri, database_name=database_name)


def create_mongo_client(
    settings: Optional[MongoSettings] = None,
    **client_options: object,
):
    """Create a lazy PyMongo client from explicit or environment settings."""

    resolved_settings = settings or MongoSettings.from_env()
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise MongoConfigurationError(
            "PyMongo is required for MongoDB access; install requirements.txt"
        ) from exc

    return MongoClient(resolved_settings.uri, **client_options)


def get_database(
    client: object,
    database_name: Optional[str] = None,
):
    """Return a database handle from a PyMongo client-like object."""

    if not database_name:
        raise MongoConfigurationError("database name is required")
    return client[database_name]


def connect_database(
    settings: Optional[MongoSettings] = None,
    **client_options: object,
):
    """Return ``(client, database)`` without forcing an eager network call."""

    resolved_settings = settings or MongoSettings.from_env()
    client = create_mongo_client(resolved_settings, **client_options)
    return client, get_database(client, resolved_settings.database_name)
