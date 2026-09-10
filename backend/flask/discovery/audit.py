"""Holistic, narrow-only audit of one competitor's discovery suggestions."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from backend.flask.llm_provider import (
    LLMProvider,
    LLMProviderConfigurationError,
    OpenAIProvider,
    OPENAI_MODEL_ENV_VAR,
)


CORE_PAGE_TYPES = (
    "BLOG",
    "NEWS",
    "PRICING",
    "PRODUCTS",
    "SERVICES",
    "PRESS",
)
AUDIT_MODEL_ENV_VAR = "DISCOVERY_AUDIT_MODEL"
DEFAULT_AUDIT_MODEL = "gpt-4o"


class DiscoveryAuditError(ValueError):
    """Raised when an audit provider returns an invalid structured result."""


class DiscoveryAuditConfigurationError(DiscoveryAuditError):
    """Raised when the audit provider cannot be configured."""


@dataclass(frozen=True)
class SuggestedCandidateForAudit:
    """Lightweight metadata for one candidate already suggested by pass one."""

    url: str
    page_type: str
    title: str | None = None
    meta_description: str | None = None


@dataclass(frozen=True)
class RedundancyFlag:
    url: str
    reason: str


@dataclass(frozen=True)
class MissingCategoryFlag:
    page_type: str
    reason: str


@dataclass(frozen=True)
class DiscoveryAuditResult:
    """The only actions an audit is allowed to request."""

    flagged_redundant: tuple[RedundancyFlag, ...] = ()
    flagged_missing_categories: tuple[MissingCategoryFlag, ...] = ()


class DiscoveryAuditClassifier(Protocol):
    """One holistic audit request for one competitor discovery run."""

    def audit(
        self,
        candidates: Sequence[SuggestedCandidateForAudit],
        *,
        homepage_title: str | None,
        homepage_meta_description: str | None,
    ) -> DiscoveryAuditResult:
        """Return redundancy and missing-category flags only."""


_OPENAI_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "discovery_second_pass_audit",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "flagged_redundant": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "url": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["url", "reason"],
                },
            },
            "flagged_missing_categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "page_type": {
                            "type": "string",
                            "enum": list(CORE_PAGE_TYPES),
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["page_type", "reason"],
                },
            },
        },
        "required": ["flagged_redundant", "flagged_missing_categories"],
    },
}

_OPENAI_INSTRUCTIONS = """You perform one holistic second-pass audit of a production
competitor's already-classified SUGGESTED discovery list.

Review the complete list together, using each candidate's URL, page type, title,
and meta description plus the competitor homepage title/meta description for
business context. The fixed core types are BLOG, NEWS, PRICING, PRODUCTS,
SERVICES, and PRESS.

For flagged_redundant, flag only a narrow or duplicate SUGGESTED entry that is
actually covered by another entry in the supplied list. Give the specific
overlap in the reason and use high-confidence language. Do not discard a page
merely because it is a specialized service, location, or product variant. A
broader SERVICES or PRODUCTS page does not make a distinct child page redundant
by itself; leave that child SUGGESTED unless the supplied metadata clearly shows
it is only a filtered/parameter variant or an actual duplicate. If unsure, do
not flag it. Reasons based on "likely", "possibly", "could", or similar
speculation are not actionable.

For flagged_missing_categories, use a high-confidence plausibility test, not a
mechanical presence check. A missing category is flaggable only when BOTH are
true: (1) the homepage metadata or the supplied candidate metadata contains
positive evidence that this business explicitly references or strongly implies
that category, and (2) no supplied SUGGESTED candidate represents it. Quote or
describe that positive evidence in the reason. The absence of a category by
itself is never evidence and must produce no flag. In particular, a service,
consulting, or agency business should not be flagged for missing PRODUCTS unless
the evidence says it sells products, an ecommerce catalog, or a retail range;
the same business may reasonably have no NEWS, PRICING, or PRESS page. A retailer
may plausibly have PRODUCTS, but still do not flag BLOG, NEWS, PRICING, or PRESS
without positive evidence. When business shape is ambiguous, omit the flag.

This pass is strictly narrowing and cannot add anything. Never invent a URL,
flag a URL that is not in the supplied SUGGESTED list, or promote a discarded
candidate. Missing-category flags are informational only. Return both arrays,
even when either array is empty, and prefer an empty array over speculative noise."""


class NoopDiscoveryAudit:
    """Safe local fallback when no audit provider is configured."""

    def audit(
        self,
        candidates: Sequence[SuggestedCandidateForAudit],
        *,
        homepage_title: str | None,
        homepage_meta_description: str | None,
    ) -> DiscoveryAuditResult:
        return DiscoveryAuditResult()


class OpenAIDiscoveryAudit:
    """Run the one-per-competitor holistic audit through the shared provider."""

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        api_key: str | None = None,
        model: str = DEFAULT_AUDIT_MODEL,
        client: Any | None = None,
        max_output_tokens: int = 2048,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise DiscoveryAuditConfigurationError("audit model must be non-empty")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise DiscoveryAuditConfigurationError(
                "max_output_tokens must be a positive integer"
            )
        if provider is not None and any(value is not None for value in (api_key, client)):
            raise DiscoveryAuditConfigurationError(
                "provide either provider or api_key/client, not both"
            )
        self.model = model.strip()
        self.max_output_tokens = max_output_tokens
        self.call_count = 0
        if provider is not None:
            self.provider = provider
            return
        try:
            self.provider = OpenAIProvider(
                api_key=api_key,
                model=self.model,
                client=client,
                max_output_tokens=max_output_tokens,
            )
        except LLMProviderConfigurationError as exc:
            raise DiscoveryAuditConfigurationError(str(exc)) from exc

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        client: Any | None = None,
        max_output_tokens: int = 2048,
    ) -> "OpenAIDiscoveryAudit":
        values: Mapping[str, str]
        if environ is None:
            _load_dotenv()
            values = os.environ
        else:
            values = environ
        model = (
            values.get(AUDIT_MODEL_ENV_VAR)
            or values.get(OPENAI_MODEL_ENV_VAR)
            or DEFAULT_AUDIT_MODEL
        )
        try:
            provider = OpenAIProvider.from_env(
                values,
                model=model,
                client=client,
                max_output_tokens=max_output_tokens,
            )
        except LLMProviderConfigurationError as exc:
            raise DiscoveryAuditConfigurationError(str(exc)) from exc
        return cls(provider=provider, model=model, max_output_tokens=max_output_tokens)

    def audit(
        self,
        candidates: Sequence[SuggestedCandidateForAudit],
        *,
        homepage_title: str | None,
        homepage_meta_description: str | None,
    ) -> DiscoveryAuditResult:
        request = {
            "suggested_candidates": [
                {
                    "url": candidate.url,
                    "page_type": candidate.page_type,
                    "title": candidate.title,
                    "meta_description": candidate.meta_description,
                }
                for candidate in candidates
            ],
            "homepage": {
                "title": homepage_title,
                "meta_description": homepage_meta_description,
            },
            "core_page_types": list(CORE_PAGE_TYPES),
        }
        self.call_count += 1
        try:
            payload = self.provider.generate_json(
                json.dumps(request, ensure_ascii=False),
                instructions=_OPENAI_INSTRUCTIONS,
                response_format=_OPENAI_RESPONSE_FORMAT,
            )
        except Exception as exc:
            raise DiscoveryAuditError("discovery audit request failed") from exc
        return _parse_audit_result(payload)


def _parse_audit_result(payload: Any) -> DiscoveryAuditResult:
    if not isinstance(payload, Mapping):
        raise DiscoveryAuditError("discovery audit response must be an object")
    redundant = payload.get("flagged_redundant")
    missing = payload.get("flagged_missing_categories")
    if not isinstance(redundant, list) or not isinstance(missing, list):
        raise DiscoveryAuditError(
            "discovery audit response must contain both flag arrays"
        )

    redundant_flags: list[RedundancyFlag] = []
    for item in redundant:
        if not isinstance(item, Mapping):
            raise DiscoveryAuditError("redundancy flags must be objects")
        url = item.get("url")
        reason = item.get("reason")
        if not _non_empty_text(url) or not _non_empty_text(reason):
            raise DiscoveryAuditError("redundancy flags require url and reason")
        redundant_flags.append(RedundancyFlag(url=url.strip(), reason=reason.strip()))

    missing_flags: list[MissingCategoryFlag] = []
    for item in missing:
        if not isinstance(item, Mapping):
            raise DiscoveryAuditError("missing-category flags must be objects")
        page_type = item.get("page_type")
        reason = item.get("reason")
        if (
            not _non_empty_text(page_type)
            or page_type.strip() not in CORE_PAGE_TYPES
            or not _non_empty_text(reason)
        ):
            raise DiscoveryAuditError(
                "missing-category flags require a core page_type and reason"
            )
        missing_flags.append(
            MissingCategoryFlag(page_type=page_type.strip(), reason=reason.strip())
        )
    return DiscoveryAuditResult(
        flagged_redundant=tuple(redundant_flags),
        flagged_missing_categories=tuple(missing_flags),
    )


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


__all__ = [
    "AUDIT_MODEL_ENV_VAR",
    "CORE_PAGE_TYPES",
    "DEFAULT_AUDIT_MODEL",
    "DiscoveryAuditClassifier",
    "DiscoveryAuditConfigurationError",
    "DiscoveryAuditError",
    "DiscoveryAuditResult",
    "MissingCategoryFlag",
    "NoopDiscoveryAudit",
    "OpenAIDiscoveryAudit",
    "RedundancyFlag",
    "SuggestedCandidateForAudit",
]
