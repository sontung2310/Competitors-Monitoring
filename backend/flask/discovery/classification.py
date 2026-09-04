"""Rule-first candidate classification with an injectable fallback boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse

from .normalization import INDEX_TYPE_VARIANTS


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
OPENAI_API_KEY_ENV_VAR = "OPENAI_KEY"
_ALLOWED_PAGE_TYPES = (
    "PRICING",
    "BLOG",
    "NEWS",
    "PRODUCTS",
    "PRESS",
    "CAREERS",
    "TEAM",
    "CEO",
    "ABOUT",
    "SERVICES",
    "CASE_STUDIES",
    "SUCCESS_STORIES",
    "TESTIMONIALS",
    "REVIEWS",
    "INDUSTRIES",
    "CONTACT",
    "WORK",
    "RESULTS",
    "PORTFOLIO",
    "PACKAGES",
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

_OPENAI_INSTRUCTIONS = """You classify unresolved Layer 1 website candidates for a competitor-monitoring system.

Use only the candidate URL, page title, and discovery source as evidence. Mark a
candidate SUGGESTED when it is likely to be a meaningful competitor page worth
reviewing or monitoring. Mark it DISCARDED when it is likely to be generic
navigation, authentication, a legal/privacy page, a utility endpoint, or an
irrelevant asset. Choose the most useful coarse page type for each candidate.
Return one classification for every candidate and do not invent URLs."""


class OpenAIClassifier:
    """Classify unresolved candidates with OpenAI's structured Responses API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_CLASSIFIER_MODEL,
        client: Any | None = None,
        max_output_tokens: int = 2048,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise OpenAIClassifierConfigurationError("classifier model must be non-empty")
        if not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise OpenAIClassifierConfigurationError(
                "max_output_tokens must be a positive integer"
            )
        if client is None:
            if not api_key or not api_key.strip():
                raise OpenAIClassifierConfigurationError(
                    f"{OPENAI_API_KEY_ENV_VAR} is not configured"
                )
            client = _create_openai_client(api_key)
        self.client = client
        self.model = model.strip()
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        client: Any | None = None,
        max_output_tokens: int = 2048,
    ) -> "OpenAIClassifier":
        """Build the provider from ``.env``/environment configuration.

        Explicit process environment variables win over values in ``.env``.
        The file is loaded only when this factory is used, so importing the
        discovery package never requires provider configuration.
        """

        if environ is None:
            _load_dotenv()
            values: Mapping[str, str] = os.environ
        else:
            values = environ
        return cls(
            api_key=values.get(OPENAI_API_KEY_ENV_VAR),
            model=values.get(CLASSIFIER_MODEL_ENV_VAR, DEFAULT_CLASSIFIER_MODEL),
            client=client,
            max_output_tokens=max_output_tokens,
        )

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
                "sources": list(candidate.sources),
            }
            for candidate in candidates
        ]
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=_OPENAI_INSTRUCTIONS,
                input=json.dumps(
                    {"candidates": request_candidates},
                    ensure_ascii=False,
                ),
                text={"format": _OPENAI_RESPONSE_FORMAT},
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
        except Exception as exc:
            raise ClassificationError("OpenAI classification request failed") from exc

        try:
            payload = json.loads(_response_output_text(response))
        except (JSONDecodeError, TypeError, ValueError) as exc:
            raise ClassificationError(
                "OpenAI classification response was not valid JSON"
            ) from exc

        results = _parse_openai_results(payload)
        _validate_fallback_results(candidates, results)
        return tuple(results)


def _create_openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIClassifierConfigurationError(
            "the openai package is required for OpenAIClassifier"
        ) from exc
    return OpenAI(api_key=api_key)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


def _response_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise ClassificationError("OpenAI classification response had no output text")
    return output_text


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
    """Classify only from exact, known URL path variants without an LLM call."""

    segments = [
        segment.lower()
        for segment in urlparse(candidate.url).path.split("/")
        if segment
    ]
    if segments:
        last_segment = segments[-1]
        for page_type, variants in INDEX_TYPE_VARIANTS.items():
            if last_segment in variants:
                return ClassificationResult(
                    url=candidate.url,
                    page_type=page_type,
                    discovery_status="SUGGESTED",
                    classification_method="RULE",
                )

    if segments:
        item_page_types = {
            "product": "PRODUCTS",
            "products": "PRODUCTS",
            "package": "PACKAGES",
            "packages": "PACKAGES",
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
) -> tuple[ClassificationResult, ...]:
    """Apply rules first and batch all unresolved candidates to the fallback."""

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

    fallback_results: Sequence[ClassificationResult] = ()
    if unresolved:
        fallback_results = fallback_classifier.classify(tuple(unresolved))
    _validate_fallback_results(unresolved, fallback_results)
    all_results = {**rule_results, **{result.url: result for result in fallback_results}}
    return tuple(all_results[candidate.url] for candidate in candidates)


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
