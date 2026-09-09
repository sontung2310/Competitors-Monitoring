"""Pluggable content processors for Layer 2 monitoring.

This module defines the processor boundary introduced in roadmap item 1.12.
The module contains the whole-page ``TextBlobProcessor`` and the deterministic
structured ``ProductListingProcessor`` for product-listing pages. LLM-based
fixture generation remains a separate verification concern.

The low-level monitoring functions live in ``website_monitoring.service``. They
are imported inside ``TextBlobProcessor.process`` rather than at module import
time so this boundary can be used by that service without creating an import
cycle.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ProcessResult:
    """Canonical output returned by every content processor."""

    changed: bool
    snapshot_content: str
    change_events: list[dict[str, str]]


class ContentProcessor(Protocol):
    """Process fetched content against the previous compatible snapshot."""

    def process(
        self,
        raw_content: str,
        previous_snapshot: Mapping[str, Any] | None,
    ) -> ProcessResult:
        """Return canonical snapshot content and zero or more change events."""


class ContentProcessingError(RuntimeError):
    """Raised when a processor cannot compare its input safely."""


class TextBlobProcessor:
    """Preserve the existing whole-page normalize/hash/diff behavior."""

    def __init__(self, *, page_type: str = "OTHER") -> None:
        if not isinstance(page_type, str) or not page_type.strip():
            raise ValueError("page_type must be a non-empty string")
        self.page_type = page_type.strip().upper()

    def process(
        self,
        raw_content: str,
        previous_snapshot: Mapping[str, Any] | None,
    ) -> ProcessResult:
        """Normalize, hash, compare, and generate the existing single event."""

        from backend.flask.change_detection.service import (
            derive_change_type,
            summarize_diff,
        )
        from .service import (
            compare_hashes,
            generate_diff,
            hash_content,
            normalize_content,
        )

        normalized_content = normalize_content(raw_content)
        if previous_snapshot is None:
            return ProcessResult(
                changed=False,
                snapshot_content=normalized_content,
                change_events=[],
            )
        if not isinstance(previous_snapshot, Mapping):
            raise TypeError("previous_snapshot must be a mapping or None")

        previous_hash = previous_snapshot.get("content_hash")
        current_hash = hash_content(normalized_content)
        if isinstance(previous_hash, str) and previous_hash.strip() and compare_hashes(
            previous_hash,
            current_hash,
        ):
            return ProcessResult(
                changed=False,
                snapshot_content=normalized_content,
                change_events=[],
            )

        previous_content = _previous_content(previous_snapshot)
        if not isinstance(previous_hash, str) or not previous_hash.strip():
            previous_hash = hash_content(previous_content)
            if compare_hashes(previous_hash, current_hash):
                return ProcessResult(
                    changed=False,
                    snapshot_content=normalized_content,
                    change_events=[],
                )

        diff = generate_diff(
            _diff_text(previous_content),
            _diff_text(normalized_content),
        )
        if not diff:
            raise ContentProcessingError(
                "snapshot hashes differ but generate_diff returned no content"
            )

        change_type = derive_change_type(self.page_type)
        return ProcessResult(
            changed=True,
            snapshot_content=normalized_content,
            change_events=[
                {
                    "change_type": change_type,
                    "summary": summarize_diff(change_type, diff),
                }
            ],
        )


@dataclass
class _ProductHTMLNode:
    """Small dependency-free DOM node used for product-card extraction."""

    tag: str
    attributes: dict[str, str]
    children: list["_ProductHTMLNode"]
    text_parts: list[str]

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()

    def text_content(self) -> str:
        values = list(self.text_parts)
        for child in self.children:
            values.append(child.text_content())
        return " ".join(" ".join(values).split())


_VOID_HTML_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_PRODUCT_CARD_CLASS = "productListItem"
_PRODUCT_LINK_CLASS = "itemImage"
_PRODUCT_TITLE_CLASS = "itemTitle"
_PRODUCT_PRICE_CLASS = "itemPrice"
_PRODUCT_LINK_DATA_ATTRIBUTE = "data-e2e"
_PRODUCT_LINK_DATA_VALUE = "plp-productList-link"
_SKIPPED_PRODUCT_MARKUP_TAGS = frozenset({"script", "style", "template", "noscript"})
_PRICE_PATTERN = re.compile(
    r"(?i)(?:a\$|au\$|aud\s*|\$)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
)
_CURRENT_PRICE_PATTERN = re.compile(
    r"(?i)\b(?:now|current|sale(?:\s+price)?)\s*:?\s*"
    r"(?:a\$|au\$|aud\s*|\$)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
)


class _ProductHTMLParser(HTMLParser):
    """Parse only enough HTML structure to identify repeated product cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _ProductHTMLNode("__root__", {}, [], [])
        self._stack: list[_ProductHTMLNode] = [self.root]
        self._skipped_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.lower()
        if self._skipped_depth:
            if normalized_tag not in _VOID_HTML_TAGS:
                self._skipped_depth += 1
            return
        if normalized_tag in _SKIPPED_PRODUCT_MARKUP_TAGS:
            self._skipped_depth = 1
            return
        node = _ProductHTMLNode(
            normalized_tag,
            {name.lower(): value or "" for name, value in attrs if name},
            [],
            [],
        )
        self._stack[-1].children.append(node)
        if normalized_tag not in _VOID_HTML_TAGS:
            self._stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._skipped_depth:
            return
        normalized_tag = tag.lower()
        self._stack[-1].children.append(
            _ProductHTMLNode(
                normalized_tag,
                {name.lower(): value or "" for name, value in attrs if name},
                [],
                [],
            )
        )

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if self._skipped_depth:
            self._skipped_depth -= 1
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == normalized_tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not self._skipped_depth:
            self._stack[-1].text_parts.append(data)

    def handle_comment(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return


def extract_products(raw_content: str) -> list[dict[str, str]]:
    """Extract deterministic products from repeated product-card markup.

    The JD Sports AU sale page uses ``li.productListItem`` cards. The stable
    product URL in the ``.itemImage`` link is the key; names are display data,
    not identifiers. ``.itemPrice`` contains both ``Was`` and ``Now`` prices,
    so the current payable ``Now`` value is tracked. When a card has no
    ``Now`` label, the last currency amount is used as the current price.

    Cards without a stable URL, name, or price are ignored rather than guessed.
    This prevents surrounding navigation, consent markup, and incomplete lazy
    loading placeholders from becoming products.
    """

    if not isinstance(raw_content, str):
        raise TypeError("raw_content must be a string")
    parser = _ProductHTMLParser()
    parser.feed(raw_content)
    parser.close()

    products_by_key: dict[str, dict[str, str]] = {}
    for card in (
        node
        for node in parser.root.descendants()
        if _has_class(node, _PRODUCT_CARD_CLASS)
    ):
        link = _first_descendant(
            card,
            lambda node: (
                node.tag == "a"
                and (
                    _has_class(node, _PRODUCT_LINK_CLASS)
                    or node.attributes.get(_PRODUCT_LINK_DATA_ATTRIBUTE) == _PRODUCT_LINK_DATA_VALUE
                )
                and bool(node.attributes.get("href"))
            ),
        )
        if link is None:
            continue
        key = _product_url_key(link.attributes["href"])
        if not key:
            continue

        title = _first_descendant(card, lambda node: _has_class(node, _PRODUCT_TITLE_CLASS))
        name = title.text_content() if title is not None else ""
        if not name:
            image = _first_descendant(card, lambda node: node.tag == "img" and node.attributes.get("alt"))
            name = image.attributes.get("alt", "").strip() if image is not None else ""

        price_node = _first_descendant(card, lambda node: _has_class(node, _PRODUCT_PRICE_CLASS))
        price = _current_price(price_node.text_content() if price_node is not None else "")
        if not name or price is None:
            continue
        products_by_key.setdefault(key, {"key": key, "name": name, "price": price})

    return [products_by_key[key] for key in sorted(products_by_key)]


def diff_by_key(
    previous_products: list[Mapping[str, Any]],
    current_products: list[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Return deterministic product events by stable product URL key."""

    previous = _index_products(previous_products, "previous_products")
    current = _index_products(current_products, "current_products")
    events: list[dict[str, str]] = []

    for key in sorted(current.keys() - previous.keys()):
        product = current[key]
        events.append(
            {
                "change_type": "NEW_PRODUCT",
                "summary": f"NEW_PRODUCT: {product['name']} ({product['price']}) at {key}",
                "detected_url": key,
                "key": key,
                "name": product["name"],
                "price": product["price"],
            }
        )
    for key in sorted(previous.keys() - current.keys()):
        product = previous[key]
        events.append(
            {
                "change_type": "PRODUCT_REMOVED",
                "summary": f"PRODUCT_REMOVED: {product['name']} ({product['price']}) at {key}",
                "detected_url": key,
                "key": key,
                "name": product["name"],
                "price": product["price"],
            }
        )
    for key in sorted(previous.keys() & current.keys()):
        old_product = previous[key]
        new_product = current[key]
        if old_product["price"] == new_product["price"]:
            continue
        events.append(
            {
                "change_type": "PRICE_CHANGE",
                "summary": (
                    f"PRICE_CHANGE: {new_product['name']} at {key}: "
                    f"{old_product['price']} -> {new_product['price']}"
                ),
                "detected_url": key,
                "key": key,
                "name": new_product["name"],
                "price": new_product["price"],
                "previous_price": old_product["price"],
            }
        )
    return events


class ProductListingProcessor:
    """Process ``PRODUCT_LISTING`` pages as a canonical keyed product list."""

    def process(
        self,
        raw_content: str,
        previous_snapshot: Mapping[str, Any] | None,
    ) -> ProcessResult:
        products = extract_products(raw_content)
        snapshot_content = _serialize_products(products)
        if previous_snapshot is None:
            return ProcessResult(False, snapshot_content, [])
        if not isinstance(previous_snapshot, Mapping):
            raise TypeError("previous_snapshot must be a mapping or None")

        previous_content = _previous_content(previous_snapshot)
        previous_products = _deserialize_products(previous_content)
        current_hash = _content_hash(snapshot_content)
        previous_hash = previous_snapshot.get("content_hash")
        if not isinstance(previous_hash, str) or not previous_hash.strip():
            previous_hash = _content_hash(previous_content)
        if _hashes_match(previous_hash, current_hash):
            return ProcessResult(False, snapshot_content, [])

        events = diff_by_key(previous_products, products)
        return ProcessResult(
            changed=True,
            snapshot_content=snapshot_content,
            change_events=events,
        )


def _has_class(node: _ProductHTMLNode, class_name: str) -> bool:
    return class_name in node.attributes.get("class", "").split()


def _first_descendant(
    node: _ProductHTMLNode,
    predicate,
) -> _ProductHTMLNode | None:
    return next((candidate for candidate in node.descendants() if predicate(candidate)), None)


def _product_url_key(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = parsed.path or value.strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path}"
    path = re.sub(r"/{2,}", "/", path)
    return path.rstrip("/") or "/"


def _current_price(value: str) -> str | None:
    current_match = _CURRENT_PRICE_PATTERN.search(value)
    amount = current_match.group(1) if current_match else None
    if amount is None:
        all_matches = _PRICE_PATTERN.findall(value)
        amount = all_matches[-1] if all_matches else None
    if amount is None:
        return None
    try:
        return f"{Decimal(amount.replace(',', '')).quantize(Decimal('0.01')):.2f}"
    except (InvalidOperation, ValueError):
        return None


def _index_products(
    products: list[Mapping[str, Any]],
    label: str,
) -> dict[str, dict[str, str]]:
    if not isinstance(products, list):
        raise TypeError(f"{label} must be a list")
    indexed: dict[str, dict[str, str]] = {}
    for product in products:
        if not isinstance(product, Mapping):
            raise TypeError(f"{label} entries must be mappings")
        key = product.get("key")
        name = product.get("name")
        price = product.get("price")
        if not all(isinstance(value, str) and value.strip() for value in (key, name, price)):
            raise ValueError(f"{label} entries require non-empty key, name, and price")
        indexed[key] = {"key": key, "name": name, "price": price}
    return indexed


def _serialize_products(products: list[Mapping[str, str]]) -> str:
    return json.dumps(products, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _deserialize_products(content: str) -> list[dict[str, str]]:
    try:
        decoded = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContentProcessingError(
            "previous PRODUCT_LISTING snapshot is not valid canonical JSON"
        ) from exc
    if not isinstance(decoded, list):
        raise ContentProcessingError(
            "previous PRODUCT_LISTING snapshot must contain a product list"
        )
    return list(_index_products(decoded, "previous snapshot").values())


def _content_hash(content: str) -> str:
    from .service import hash_content

    return hash_content(content)


def _hashes_match(previous_hash: Any, current_hash: str) -> bool:
    from .service import compare_hashes

    return isinstance(previous_hash, str) and compare_hashes(previous_hash, current_hash)


def resolve_content_processor(
    page_type: str,
    processors: Mapping[str, ContentProcessor] | None = None,
) -> ContentProcessor:
    """Resolve a processor by page type, defaulting to ``TextBlobProcessor``."""

    if not isinstance(page_type, str) or not page_type.strip():
        raise ValueError("page_type must be a non-empty string")
    normalized_page_type = page_type.strip().upper()
    configured = processors or {}
    processor = configured.get(normalized_page_type)
    if processor is not None:
        return processor
    if normalized_page_type == "PRODUCT_LISTING":
        return ProductListingProcessor()
    return TextBlobProcessor(page_type=normalized_page_type)


def _previous_content(snapshot: Mapping[str, Any]) -> str:
    for field in ("content", "normalized_content"):
        content = snapshot.get(field)
        if isinstance(content, str):
            return content
    raise ContentProcessingError(
        "previous snapshot content is unavailable; inject a snapshot content loader"
    )


def _diff_text(content: str) -> str:
    """Give line-oriented diffs a terminator without changing page content."""

    return content if content.endswith("\n") else f"{content}\n"


__all__ = [
    "ContentProcessingError",
    "ContentProcessor",
    "ProductListingProcessor",
    "ProcessResult",
    "TextBlobProcessor",
    "diff_by_key",
    "extract_products",
    "resolve_content_processor",
]
