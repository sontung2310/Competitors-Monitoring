"""DynamoDB client/table-name configuration for production storage.

Mirrors ``database/connection.py``'s environment-variable pattern for Mongo.
Region reuses ``AWS_REGION``, already required by the SQS worker.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


class DynamoDBConfigurationError(RuntimeError):
    """Raised when the application cannot construct a DynamoDB connection."""


@dataclass(frozen=True)
class DynamoDBSettings:
    """Runtime settings required to reach the two production tables."""

    region: str
    monitoring_targets_table: str
    snapshots_table: str

    @classmethod
    def from_env(
        cls,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "DynamoDBSettings":
        values = environ if environ is not None else os.environ
        region = values.get("AWS_REGION", "").strip()
        monitoring_targets_table = values.get(
            "AWS_DYNAMODB_MONITORING_TARGETS_TABLE", ""
        ).strip()
        snapshots_table = values.get("AWS_DYNAMODB_SNAPSHOTS_TABLE", "").strip()
        if not region:
            raise DynamoDBConfigurationError("AWS_REGION is not configured")
        if not monitoring_targets_table:
            raise DynamoDBConfigurationError(
                "AWS_DYNAMODB_MONITORING_TARGETS_TABLE is not configured"
            )
        if not snapshots_table:
            raise DynamoDBConfigurationError(
                "AWS_DYNAMODB_SNAPSHOTS_TABLE is not configured"
            )
        return cls(
            region=region,
            monitoring_targets_table=monitoring_targets_table,
            snapshots_table=snapshots_table,
        )


def create_dynamodb_client(settings: Optional[DynamoDBSettings] = None, **client_options: object):
    """Create a boto3 DynamoDB client from explicit or environment settings."""

    resolved = settings or DynamoDBSettings.from_env()
    try:
        import boto3
    except ImportError as exc:
        raise DynamoDBConfigurationError(
            "boto3 is required for DynamoDB access; install requirements.txt"
        ) from exc
    return boto3.client("dynamodb", region_name=resolved.region, **client_options)


def create_dynamodb_resource(settings: Optional[DynamoDBSettings] = None, **resource_options: object):
    """Create a boto3 DynamoDB resource, whose ``Table`` API accepts/returns
    native Python types instead of the client's raw attribute-value maps."""

    resolved = settings or DynamoDBSettings.from_env()
    try:
        import boto3
    except ImportError as exc:
        raise DynamoDBConfigurationError(
            "boto3 is required for DynamoDB access; install requirements.txt"
        ) from exc
    return boto3.resource("dynamodb", region_name=resolved.region, **resource_options)


__all__ = [
    "DynamoDBConfigurationError",
    "DynamoDBSettings",
    "create_dynamodb_client",
    "create_dynamodb_resource",
]
