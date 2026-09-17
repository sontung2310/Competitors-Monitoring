"""A small in-memory fake of boto3's DynamoDB resource Table API.

Only implements what this project's DynamoDB repositories actually call:
put_item, get_item, delete_item, update_item, query (single-field equality,
optionally against a named GSI), and scan. Real correctness against the
actual AWS tables is covered separately by manual smoke tests; this fake
exists so the regular offline test suite can exercise the repository logic
(DISCARDED skip, mark_discarded=delete, Decimal handling, etc.) without live
credentials.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _to_dynamodb_number(value: Any) -> Any:
    """boto3's real Table API returns Decimal for every Number attribute."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return value


def _marshal(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _to_dynamodb_number(value) for key, value in item.items()}


class FakeDynamoDBTable:
    def __init__(
        self,
        key_fields: tuple[str, ...],
        *,
        gsi_key_fields: dict[str, str] | None = None,
    ) -> None:
        self.key_fields = key_fields
        self.gsi_key_fields = gsi_key_fields or {}
        self.items: list[dict[str, Any]] = []

    def _key_of(self, item: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(item[field] for field in self.key_fields)

    def put_item(self, *, Item: dict[str, Any]) -> dict[str, Any]:
        marshaled = _marshal(Item)
        key = self._key_of(marshaled)
        self.items = [existing for existing in self.items if self._key_of(existing) != key]
        self.items.append(marshaled)
        return {}

    def get_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:
        for item in self.items:
            if all(item.get(field) == value for field, value in Key.items()):
                return {"Item": dict(item)}
        return {}

    def delete_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:
        self.items = [
            item
            for item in self.items
            if not all(item.get(field) == value for field, value in Key.items())
        ]
        return {}

    def update_item(
        self,
        *,
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeNames: dict[str, str],
        ExpressionAttributeValues: dict[str, Any],
    ) -> dict[str, Any]:
        for item in self.items:
            if all(item.get(field) == value for field, value in Key.items()):
                for name_placeholder, value_placeholder in _pairs(UpdateExpression):
                    field = ExpressionAttributeNames[name_placeholder]
                    item[field] = _to_dynamodb_number(
                        ExpressionAttributeValues[value_placeholder]
                    )
                return {}
        raise AssertionError(f"update_item found no item for key {Key!r}")

    def query(
        self,
        *,
        KeyConditionExpression: Any,
        IndexName: str | None = None,
        ScanIndexForward: bool = True,
        ExclusiveStartKey: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key_object, value = KeyConditionExpression.get_expression()["values"]
        field = key_object.name
        matches = [item for item in self.items if item.get(field) == value]
        sort_fields = [f for f in self.key_fields if f != field]
        if sort_fields:
            sort_field = sort_fields[0]
            matches.sort(key=lambda item: item.get(sort_field), reverse=not ScanIndexForward)
        return {"Items": [dict(item) for item in matches]}

    def scan(self, *, ExclusiveStartKey: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"Items": [dict(item) for item in self.items]}


def _pairs(update_expression: str) -> list[tuple[str, str]]:
    # "SET #f0 = :v0, #f1 = :v1" -> [("#f0", ":v0"), ("#f1", ":v1")]
    body = update_expression.removeprefix("SET ").strip()
    result = []
    for clause in body.split(", "):
        name, value = clause.split(" = ")
        result.append((name.strip(), value.strip()))
    return result


__all__ = ["FakeDynamoDBTable"]
