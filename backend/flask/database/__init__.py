"""Shared database access utilities."""

from .base_repository import (
    BaseMongoRepository,
    InvalidIdentifierError,
    serialize_document,
    to_object_id,
    utc_now,
)
from .connection import (
    MongoConfigurationError,
    MongoSettings,
    connect_database,
    create_mongo_client,
    get_database,
)

__all__ = [
    "BaseMongoRepository",
    "InvalidIdentifierError",
    "MongoConfigurationError",
    "MongoSettings",
    "connect_database",
    "create_mongo_client",
    "get_database",
    "serialize_document",
    "to_object_id",
    "utc_now",
]
