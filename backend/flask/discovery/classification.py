"""Rule-first candidate classification with an injectable fallback boundary."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from backend.flask.llm_provider import (
    LLMProvider,
    LLMProviderConfigurationError,
    OpenAIProvider,
    OpenRouterProvider,
    OPENAI_MODEL_ENV_VAR,
    OPENROUTER_MODEL_ENV_VAR,
    DEFAULT_OPENROUTER_MODEL,
)

from .normalization import index_page_type


class ClassificationError(ValueError):
    """Raised when a fallback classifier returns an invalid result set."""


class OpenAIClassifierConfigurationError(ClassificationError):
    """Raised when the OpenAI fallback cannot be configured."""


@dataclass(frozen=True)
class CandidateForClassification:
    """Candidate context supplied to rule and fallback classifiers."""

    raw_url: str
    url: str
    title: str | None = None
    sources: tuple[str, ...] = ()
    force_discarded: bool = False
    meta_description: str | None = None


@dataclass(frozen=True)
class ClassificationResult:
    """Normalized classification output persisted with a candidate."""

    url: str
    page_type: str
    discovery_status: str
    classification_method: str


class CandidateClassifier(Protocol):
    """Interface for classifying unresolved candidates in one batch.

    Provider adapters translate this typed request into the structured JSON
    request described in the specification. The discovery service never
    depends on a provider SDK or API key.
    """

    def classify(
        self,
        candidates: Sequence[CandidateForClassification],
    ) -> Sequence[ClassificationResult]:
        """Return exactly one classification result for every input candidate."""


DEFAULT_CLASSIFIER_MODEL = "gpt-5-nano"
CLASSIFIER_MODEL_ENV_VAR = "DISCOVERY_CLASSIFIER_MODEL"
CLASSIFIER_PROVIDER_ENV_VAR = "DISCOVERY_CLASSIFIER_PROVIDER"
DEFAULT_CLASSIFIER_PROVIDER = "openai"
CLASSIFIER_BATCH_SIZE_ENV_VAR = "DISCOVERY_CLASSIFIER_BATCH_SIZE"
DEFAULT_CLASSIFIER_BATCH_SIZE = 25
OPENAI_API_KEY_ENV_VAR = "OPENAI_KEY"
_ALLOWED_PAGE_TYPES = (
    "BLOG",
    "NEWS",
    "PRICING",
    "PRODUCTS",
    "SERVICES",
    "PRESS",
    "OTHER",
)
_ALLOWED_DISCOVERY_STATUSES = ("SUGGESTED", "DISCARDED")

_OPENAI_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "layer_1_candidate_classifications",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "url": {"type": "string"},
                        "page_type": {
                            "type": "string",
                            "enum": list(_ALLOWED_PAGE_TYPES),
                        },
                        "discovery_status": {
                            "type": "string",
                            "enum": list(_ALLOWED_DISCOVERY_STATUSES),
                        },
                    },
                    "required": ["url", "page_type", "discovery_status"],
                },
            }
        },
        "required": ["classifications"],
    },
}

_OPENAI_INSTRUCTIONS = """Classify each Layer 1 website candidate for a competitor-monitoring system, using only its URL, title, meta description (optional, may be missing), and discovery source.

Mark SUGGESTED only for a page that is THE single hub/index a visitor uses to see an entire category of content: BLOG, NEWS, PRESS, PRICING, PRODUCTS, or SERVICES. Test: would this page have many near-identical siblings, each covering one offering? If yes, it is Layer 3 (one item, not the category) -- mark OTHER/DISCARDED, even when the URL or copy sounds durable, category-like, or article-like. This covers:
- a flat, descriptive slug for one service/product (e.g. "/seo-consultant-melbourne", "/virtual-cmo")
- a specific named program, package, or numbered offer (e.g. "30-Day SEO Stream", "Analytics & Tracking Stream")
- an industry/vertical-specific landing page (e.g. "Digital Marketing For Construction Companies")
- a resource/asset/template library
- a narrative "what we do" / "our approach" / "about us" page that does not itself list services
- one blog post, product, press release, case study, person, job, or campaign

Rules: pick exactly one of BLOG, NEWS, PRICING, PRODUCTS, SERVICES, PRESS, OTHER -- never invent another type, and page type alone never justifies SUGGESTED. Never suggest the homepage ("/"). When ambiguous, choose OTHER/DISCARDED. Classify every candidate given; never invent a URL."""

logger = logging.getLogger(__name__)


class OpenAIClassifier:
    """Classify unresolved candidates through the shared LLM provider.

    ``max_output_tokens`` defaults well above what the visible JSON alone
    needs: a reasoning model (the default ``gpt-5-nano``) spends part of this
    budget on internal reasoning tokens before writing any visible output, so
    a tight limit (e.g. the 2048 that was plenty for gpt-4o) truncates the
    JSON mid-string on a full-size batch instead of erroring cleanly.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        api_key: str | None = None,
        model: str = DEFAULT_CLASSIFIER_MODEL,
        client: Any | None = None,
        max_output_tokens: int = 8000,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise OpenAIClassifierConfigurationError("classifier model must be non-empty")
        if not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise OpenAIClassifierConfigurationError(
                "max_output_tokens must be a positive integer"
            )
        self.model = model.strip()
        self.max_output_tokens = max_output_tokens
        self.call_count = 0
        self.last_results: tuple[ClassificationResult, ...] = ()
        if provider is not None and any(value is not None for value in (api_key, client)):
            raise OpenAIClassifierConfigurationError(
                "provide either provider or api_key/client, not both"
            )
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
            raise OpenAIClassifierConfigurationError(str(exc)) from exc

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        client: Any | None = None,
        max_output_tokens: int = 8000,
    ) -> "OpenAIClassifier":
        """Build the provider from ``.env``/environment configuration.

        ``DISCOVERY_CLASSIFIER_PROVIDER`` picks which underlying LLM
        provider to build ("openai", the default, or "openrouter" -- e.g.
        for a cheaper model like DeepSeek). Both speak the same
        ``LLMProvider`` interface, so nothing else in the classifier needs
        to know which one is in use. Explicit process environment variables
        win over values in ``.env``. The file is loaded only when this
        factory is used, so importing the discovery package never requires
        provider configuration.
        """

        if environ is None:
            _load_dotenv()
            values: Mapping[str, str] = os.environ
        else:
            values = environ

        provider_name = (
            values.get(CLASSIFIER_PROVIDER_ENV_VAR) or DEFAULT_CLASSIFIER_PROVIDER
        ).strip().lower()
        try:
            if provider_name == "openrouter":
                model = (
                    values.get(CLASSIFIER_MODEL_ENV_VAR)
                    or values.get(OPENROUTER_MODEL_ENV_VAR)
                    or DEFAULT_OPENROUTER_MODEL
                )
                provider = OpenRouterProvider.from_env(
                    values,
                    model=model,
                    client=client,
                    max_output_tokens=max_output_tokens,
                )
            elif provider_name == "openai":
                model = (
                    values.get(CLASSIFIER_MODEL_ENV_VAR)
                    or values.get(OPENAI_MODEL_ENV_VAR)
                    or DEFAULT_CLASSIFIER_MODEL
                )
                provider = OpenAIProvider.from_env(
                    values,
                    model=model,
                    client=client,
                    max_output_tokens=max_output_tokens,
                )
            else:
                raise OpenAIClassifierConfigurationError(
                    f"{CLASSIFIER_PROVIDER_ENV_VAR} must be 'openai' or "
                    f"'openrouter', got {provider_name!r}"
                )
        except LLMProviderConfigurationError as exc:
            raise OpenAIClassifierConfigurationError(str(exc)) from exc
        return cls(provider=provider, model=model, max_output_tokens=max_output_tokens)

    def classify(
        self,
        candidates: Sequence[CandidateForClassification],
    ) -> tuple[ClassificationResult, ...]:
        """Classify all unresolved candidates in one structured API request."""

        if not candidates:
            return ()

        request_candidates = [
            {
                "raw_url": candidate.raw_url,
                "url": candidate.url,
                "title": candidate.title,
                "meta_description": candidate.meta_description,
                "sources": list(candidate.sources),
            }
            for candidate in candidates
        ]
        self.call_count += 1
        try:
            payload = self.provider.generate_json(
                json.dumps(
                    {"candidates": request_candidates},
                    ensure_ascii=False,
                ),
                instructions=_OPENAI_INSTRUCTIONS,
                response_format=_OPENAI_RESPONSE_FORMAT,
            )
        except Exception as exc:
            raise ClassificationError("OpenAI classification request failed") from exc

        results = _parse_openai_results(payload)
        _validate_fallback_results(candidates, results)
        self.last_results = tuple(results)
        return self.last_results


def _parse_openai_results(payload: Any) -> tuple[ClassificationResult, ...]:
    if not isinstance(payload, dict):
        raise ClassificationError("OpenAI classification response must be an object")
    items = payload.get("classifications")
    if not isinstance(items, list):
        raise ClassificationError(
            "OpenAI classification response must contain a classifications list"
        )

    results: list[ClassificationResult] = []
    for item in items:
        if not isinstance(item, dict):
            raise ClassificationError("each OpenAI classification must be an object")
        url = item.get("url")
        page_type = item.get("page_type")
        discovery_status = item.get("discovery_status")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (url, page_type, discovery_status)
        ):
            raise ClassificationError(
                "OpenAI classifications require non-empty string fields"
            )
        results.append(
            ClassificationResult(
                url=url,
                page_type=page_type,
                discovery_status=discovery_status,
                classification_method="LLM",
            )
        )
    return tuple(results)


def _load_dotenv() -> None:
    """Load local environment configuration without requiring python-dotenv."""

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


class DeterministicStubClassifier:
    """Deterministic fallback used by tests and local development."""

    def __init__(
        self,
        *,
        page_type: str = "OTHER",
        discovery_status: str = "DISCARDED",
    ) -> None:
        self.page_type = page_type
        self.discovery_status = discovery_status

    def classify(
        self,
        candidates: Sequence[CandidateForClassification],
    ) -> tuple[ClassificationResult, ...]:
        return tuple(
            ClassificationResult(
                url=candidate.url,
                page_type=self.page_type,
                discovery_status=self.discovery_status,
                classification_method="LLM",
            )
            for candidate in candidates
        )


def classify_by_rules(
    candidate: CandidateForClassification,
) -> ClassificationResult | None:
    """Classify only from exact, known URL path variants without an LLM call.

    The index/durable-service check is shared with ``discovery_scope`` via
    ``normalization.index_page_type`` (extension-stripping, locale-prefix
    tolerance) rather than re-implemented here, so a URL that
    ``discovery_scope`` already calls ``INDEX`` always resolves here too
    instead of needlessly falling through to the LLM.
    """

    page_type = index_page_type(candidate.url)
    if page_type is not None:
        return ClassificationResult(
            url=candidate.url,
            page_type=page_type,
            discovery_status="SUGGESTED",
            classification_method="RULE",
        )

    segments = [
        segment.lower()
        for segment in urlparse(candidate.url).path.split("/")
        if segment
    ]
    if segments:
        item_page_types = {
            "product": "PRODUCTS",
            "products": "PRODUCTS",
            "solution": "PRODUCTS",
            "solutions": "PRODUCTS",
        }
        page_type = item_page_types.get(segments[0])
        if page_type is not None:
            return ClassificationResult(
                url=candidate.url,
                page_type=page_type,
                discovery_status="SUGGESTED",
                classification_method="RULE",
            )
    return None


def classify_candidates(
    candidates: Sequence[CandidateForClassification],
    fallback_classifier: CandidateClassifier,
    *,
    batch_size: int = DEFAULT_CLASSIFIER_BATCH_SIZE,
) -> tuple[ClassificationResult, ...]:
    """Apply rules first and classify unresolved candidates in bounded batches."""

    batch_size = resolve_classifier_batch_size(batch_size)

    rule_results: dict[str, ClassificationResult] = {}
    unresolved: list[CandidateForClassification] = []
    for candidate in candidates:
        if candidate.force_discarded:
            rule_results[candidate.url] = ClassificationResult(
                url=candidate.url,
                page_type="OTHER",
                discovery_status="DISCARDED",
                classification_method="RULE",
            )
            continue
        result = classify_by_rules(candidate)
        if result is None:
            unresolved.append(candidate)
        else:
            rule_results[candidate.url] = result

    fallback_results: list[ClassificationResult] = []
    if unresolved:
        for batch_number, start in enumerate(range(0, len(unresolved), batch_size), 1):
            batch = tuple(unresolved[start : start + batch_size])
            try:
                batch_results = fallback_classifier.classify(batch)
                _validate_fallback_results(batch, batch_results)
            except Exception as exc:
                logger.warning(
                    "candidate fallback classification batch failed; retaining "
                    "batch as discarded batch=%d size=%d: %s",
                    batch_number,
                    len(batch),
                    exc,
                )
                batch_results = DeterministicStubClassifier().classify(batch)
            fallback_results.extend(batch_results)
    _validate_fallback_results(unresolved, fallback_results)
    all_results = {**rule_results, **{result.url: result for result in fallback_results}}
    return tuple(
        _coerce_other_to_discarded(all_results[candidate.url]) for candidate in candidates
    )


def _coerce_other_to_discarded(result: ClassificationResult) -> ClassificationResult:
    """Enforce page_type OTHER implies DISCARDED, regardless of classifier.

    The prompt tells the LLM this pairing is required, but nothing stops a
    model from returning OTHER + SUGGESTED anyway (observed with gpt-5-nano);
    that combination is meaningless downstream, since OTHER isn't one of the
    six tracked categories. Correct it here as a data-integrity invariant
    rather than trusting every classifier implementation to get it right.
    """

    if result.page_type == "OTHER" and result.discovery_status != "DISCARDED":
        return ClassificationResult(
            url=result.url,
            page_type=result.page_type,
            discovery_status="DISCARDED",
            classification_method=result.classification_method,
        )
    return result


def resolve_classifier_batch_size(
    batch_size: int | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Return a positive classifier batch size from an explicit value or env."""

    if batch_size is None:
        values = os.environ if environ is None else environ
        raw_value = values.get(CLASSIFIER_BATCH_SIZE_ENV_VAR)
        if raw_value is None or not raw_value.strip():
            return DEFAULT_CLASSIFIER_BATCH_SIZE
        try:
            batch_size = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ClassificationError(
                f"{CLASSIFIER_BATCH_SIZE_ENV_VAR} must be a positive integer"
            ) from exc
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ClassificationError("classifier batch_size must be a positive integer")
    return batch_size


def _validate_fallback_results(
    candidates: Sequence[CandidateForClassification],
    results: Sequence[ClassificationResult],
) -> None:
    expected_urls = [candidate.url for candidate in candidates]
    if len(expected_urls) != len(set(expected_urls)):
        raise ClassificationError("candidate URLs must be unique")
    result_urls = [result.url for result in results]
    if len(result_urls) != len(set(result_urls)):
        raise ClassificationError("fallback returned duplicate candidate URLs")
    if set(result_urls) != set(expected_urls):
        raise ClassificationError("fallback did not return exactly the unresolved candidates")
    for result in results:
        if result.classification_method != "LLM":
            raise ClassificationError("fallback results must use classification_method LLM")
        if result.discovery_status not in {"SUGGESTED", "DISCARDED"}:
            raise ClassificationError(
                "fallback discovery_status must be SUGGESTED or DISCARDED"
            )
        if result.page_type not in _ALLOWED_PAGE_TYPES:
            raise ClassificationError(
                f"fallback page_type must be one of {', '.join(_ALLOWED_PAGE_TYPES)}"
            )
        if not result.page_type.strip():
            raise ClassificationError("fallback page_type cannot be empty")
