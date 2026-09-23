"""Reusable, environment-configured LLM provider boundary.

This module owns provider SDK construction and response validation for offline
fixture generation and runtime enrichment. It deliberately has no database or
monitoring imports, so discovery and monitoring consumers can share the same
provider boundary without coupling LLM plumbing to either data path.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OPENAI_API_KEY_ENV_VAR = "OPENAI_KEY"
OPENAI_STANDARD_API_KEY_ENV_VAR = "OPENAI_API_KEY"
OPENAI_MODEL_ENV_VAR = "OPENAI_MODEL"
DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_MAX_OUTPUT_TOKENS = 4096

OPENROUTER_API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
OPENROUTER_MODEL_ENV_VAR = "OPENROUTER_MODEL"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash-0731"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

OPEN_JEV_ENDPOINT_ENV_VAR = "OPEN_JEV_ENDPOINT"
DEFAULT_OPEN_JEV_ENDPOINT = "http://127.0.0.1:8791/v1/systemone"
OPEN_JEV_MODEL_ENV_VAR = "OPEN_JEV_MODEL"
DEFAULT_OPEN_JEV_MODEL = "open-jev"
OPEN_JEV_TIMEOUT_ENV_VAR = "OPEN_JEV_TIMEOUT_SECONDS"
DEFAULT_OPEN_JEV_TIMEOUT_SECONDS = 30.0


class LLMProviderError(RuntimeError):
    """Base error for provider construction, requests, and responses."""


class LLMProviderConfigurationError(LLMProviderError):
    """Raised when the provider cannot be configured explicitly."""


class LLMProviderResponseError(LLMProviderError):
    """Raised when the provider returns missing or invalid output."""


class LLMProvider(Protocol):
    """Minimal provider contract reusable by offline tools and classifiers."""

    def generate(
        self,
        prompt: str,
        *,
        instructions: str,
        response_format: Mapping[str, Any] | None = None,
    ) -> str:
        """Generate provider output without fabricating a fallback value."""

    def generate_json(
        self,
        prompt: str,
        *,
        instructions: str,
        response_format: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Generate and parse one structured JSON object."""


class OpenAIProvider:
    """Small OpenAI Responses API adapter with no silent fallback behavior."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_OPENAI_MODEL,
        client: Any | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise LLMProviderConfigurationError("OpenAI model must be non-empty")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise LLMProviderConfigurationError(
                "max_output_tokens must be a positive integer"
            )
        if client is None:
            if not isinstance(api_key, str) or not api_key.strip():
                raise LLMProviderConfigurationError(
                    f"{OPENAI_API_KEY_ENV_VAR} or "
                    f"{OPENAI_STANDARD_API_KEY_ENV_VAR} is not configured"
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
        model: str | None = None,
        client: Any | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> "OpenAIProvider":
        """Build a provider from process environment or an explicit mapping.

        ``model`` is an optional consumer-specific override.  This keeps the
        provider's environment handling shared while allowing consumers such
        as discovery classification to use their own configured default.
        """

        if environ is None:
            _load_dotenv()
            values: Mapping[str, str] = os.environ
        else:
            values = environ
        return cls(
            api_key=(
                values.get(OPENAI_API_KEY_ENV_VAR)
                or values.get(OPENAI_STANDARD_API_KEY_ENV_VAR)
            ),
            model=model or values.get(OPENAI_MODEL_ENV_VAR, DEFAULT_OPENAI_MODEL),
            client=client,
            max_output_tokens=max_output_tokens,
        )

    def generate(
        self,
        prompt: str,
        *,
        instructions: str,
        response_format: Mapping[str, Any] | None = None,
    ) -> str:
        """Call OpenAI and return its text output or raise a useful error."""

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("LLM prompt must be non-empty")
        if not isinstance(instructions, str) or not instructions.strip():
            raise ValueError("LLM instructions must be non-empty")
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions.strip(),
            "input": prompt,
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        if response_format is not None:
            if not isinstance(response_format, Mapping):
                raise ValueError("response_format must be a mapping")
            request["text"] = {"format": dict(response_format)}
        try:
            response = self.client.responses.create(**request)
        except Exception as exc:
            raise LLMProviderError(
                f"OpenAI request failed for model {self.model!r}"
            ) from exc

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise LLMProviderResponseError(
                "OpenAI response contained no output text"
            )
        return output_text.strip()

    def generate_json(
        self,
        prompt: str,
        *,
        instructions: str,
        response_format: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Generate strict JSON and reject malformed provider output."""

        output = self.generate(
            prompt,
            instructions=instructions,
            response_format=response_format,
        )
        try:
            decoded = json.loads(_strip_code_fence(output))
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMProviderResponseError(
                "OpenAI response was not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise LLMProviderResponseError(
                "OpenAI JSON response must be an object"
            )
        return decoded


class OpenRouterProvider:
    """OpenRouter adapter, via its OpenAI-compatible Chat Completions endpoint.

    OpenRouter proxies many model providers (DeepSeek, etc.) behind one API,
    but only speaks the Chat Completions shape -- not the newer Responses
    API ``OpenAIProvider`` uses. This translates the same
    ``{"type": "json_schema", "name", "strict", "schema"}`` response_format
    a caller already builds for ``OpenAIProvider`` into Chat Completions'
    nested equivalent, so callers (e.g. the discovery classifier) stay
    provider-agnostic and don't need their own per-provider branch.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_OPENROUTER_MODEL,
        client: Any | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise LLMProviderConfigurationError("OpenRouter model must be non-empty")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise LLMProviderConfigurationError(
                "max_output_tokens must be a positive integer"
            )
        if client is None:
            if not isinstance(api_key, str) or not api_key.strip():
                raise LLMProviderConfigurationError(
                    f"{OPENROUTER_API_KEY_ENV_VAR} is not configured"
                )
            client = _create_openrouter_client(api_key)
        self.client = client
        self.model = model.strip()
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        model: str | None = None,
        client: Any | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> "OpenRouterProvider":
        if environ is None:
            _load_dotenv()
            values: Mapping[str, str] = os.environ
        else:
            values = environ
        return cls(
            api_key=values.get(OPENROUTER_API_KEY_ENV_VAR),
            model=model or values.get(OPENROUTER_MODEL_ENV_VAR, DEFAULT_OPENROUTER_MODEL),
            client=client,
            max_output_tokens=max_output_tokens,
        )

    def generate(
        self,
        prompt: str,
        *,
        instructions: str,
        response_format: Mapping[str, Any] | None = None,
    ) -> str:
        """Call OpenRouter and return its text output or raise a useful error."""

        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("LLM prompt must be non-empty")
        if not isinstance(instructions, str) or not instructions.strip():
            raise ValueError("LLM instructions must be non-empty")
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions.strip()},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.max_output_tokens,
        }
        if response_format is not None:
            if not isinstance(response_format, Mapping):
                raise ValueError("response_format must be a mapping")
            request["response_format"] = _to_chat_completions_response_format(
                response_format
            )
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            raise LLMProviderError(
                f"OpenRouter request failed for model {self.model!r}"
            ) from exc

        try:
            output_text = response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise LLMProviderResponseError(
                "OpenRouter response contained no output text"
            ) from exc
        if not isinstance(output_text, str) or not output_text.strip():
            raise LLMProviderResponseError(
                "OpenRouter response contained no output text"
            )
        return output_text.strip()

    def generate_json(
        self,
        prompt: str,
        *,
        instructions: str,
        response_format: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Generate strict JSON and reject malformed provider output."""

        output = self.generate(
            prompt,
            instructions=instructions,
            response_format=response_format,
        )
        try:
            decoded = json.loads(_strip_code_fence(output))
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMProviderResponseError(
                "OpenRouter response was not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise LLMProviderResponseError(
                "OpenRouter JSON response must be an object"
            )
        return decoded


class OpenJevProvider:
    """HTTP adapter for a local Open-Jev typed-decision server.

    Open-Jev does not generate JSON text. It returns an ``answers`` mapping
    containing typed decisions, so this provider deliberately exposes ``ask``
    instead of pretending to implement the text-generation provider contract.
    """

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_OPEN_JEV_ENDPOINT,
        model: str = DEFAULT_OPEN_JEV_MODEL,
        timeout_seconds: float = DEFAULT_OPEN_JEV_TIMEOUT_SECONDS,
        opener: Any | None = None,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise LLMProviderConfigurationError(
                "Open-Jev endpoint must be a non-empty URL"
            )
        if not isinstance(model, str) or not model.strip():
            raise LLMProviderConfigurationError("Open-Jev model must be non-empty")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or not math.isfinite(timeout_seconds)
        ):
            raise LLMProviderConfigurationError(
                "Open-Jev timeout_seconds must be positive"
            )
        self.endpoint = endpoint.strip()
        self.model = model.strip()
        self.timeout_seconds = float(timeout_seconds)
        self.opener = urlopen if opener is None else opener

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        opener: Any | None = None,
    ) -> "OpenJevProvider":
        if environ is None:
            _load_dotenv()
            values: Mapping[str, str] = os.environ
        else:
            values = environ

        raw_timeout = values.get(
            OPEN_JEV_TIMEOUT_ENV_VAR,
            str(DEFAULT_OPEN_JEV_TIMEOUT_SECONDS),
        )
        try:
            timeout_seconds = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise LLMProviderConfigurationError(
                f"{OPEN_JEV_TIMEOUT_ENV_VAR} must be positive"
            ) from exc
        return cls(
            endpoint=values.get(OPEN_JEV_ENDPOINT_ENV_VAR, DEFAULT_OPEN_JEV_ENDPOINT),
            model=values.get(OPEN_JEV_MODEL_ENV_VAR, DEFAULT_OPEN_JEV_MODEL),
            timeout_seconds=timeout_seconds,
            opener=opener,
        )

    def ask(
        self,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if not isinstance(state, Mapping):
            raise ValueError("Open-Jev state must be a mapping")
        if not isinstance(questions, Mapping) or not questions:
            raise ValueError("Open-Jev questions must be a non-empty mapping")

        body = json.dumps(
            {
                "model": self.model,
                "state": dict(state),
                "questions": dict(questions),
            },
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                raw_response = response.read()
        except HTTPError as exc:
            raise LLMProviderError(
                f"Open-Jev request failed with HTTP {exc.code}"
            ) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise LLMProviderError("Open-Jev request failed") from exc

        try:
            decoded = json.loads(raw_response)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMProviderResponseError(
                "Open-Jev response was not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise LLMProviderResponseError(
                "Open-Jev response must be an object"
            )
        if "error" in decoded:
            raise LLMProviderResponseError(
                f"Open-Jev response contained an error: {decoded['error']}"
            )
        return decoded


def _to_chat_completions_response_format(
    response_format: Mapping[str, Any],
) -> dict[str, Any]:
    """Translate a Responses-API-shaped json_schema format into the nested
    Chat Completions shape OpenRouter (and OpenAI's own Chat Completions
    API) expect. Anything else passes through unchanged."""

    if response_format.get("type") != "json_schema":
        return dict(response_format)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_format.get("name", "response"),
            "strict": response_format.get("strict", True),
            "schema": response_format.get("schema", {}),
        },
    }


def _create_openrouter_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMProviderConfigurationError(
            "the openai package is required for OpenRouterProvider"
        ) from exc
    return OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)


def _create_openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMProviderConfigurationError(
            "the openai package is required for OpenAIProvider"
        ) from exc
    return OpenAI(api_key=api_key)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


def _strip_code_fence(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_OPENAI_MODEL",
    "DEFAULT_OPENROUTER_MODEL",
    "LLMProvider",
    "LLMProviderConfigurationError",
    "LLMProviderError",
    "LLMProviderResponseError",
    "OPENAI_API_KEY_ENV_VAR",
    "OPENAI_STANDARD_API_KEY_ENV_VAR",
    "OPENAI_MODEL_ENV_VAR",
    "OPENROUTER_API_KEY_ENV_VAR",
    "OPENROUTER_MODEL_ENV_VAR",
    "OPENROUTER_BASE_URL",
    "OPEN_JEV_ENDPOINT_ENV_VAR",
    "DEFAULT_OPEN_JEV_ENDPOINT",
    "OPEN_JEV_MODEL_ENV_VAR",
    "DEFAULT_OPEN_JEV_MODEL",
    "OPEN_JEV_TIMEOUT_ENV_VAR",
    "DEFAULT_OPEN_JEV_TIMEOUT_SECONDS",
    "OpenAIProvider",
    "OpenRouterProvider",
    "OpenJevProvider",
]
