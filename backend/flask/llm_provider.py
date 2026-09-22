"""Reusable, environment-configured LLM provider boundary.

This module owns provider SDK construction and response validation for offline
fixture generation and runtime enrichment. It deliberately has no database or
monitoring imports, so discovery and monitoring consumers can share the same
provider boundary without coupling LLM plumbing to either data path.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Protocol


OPENAI_API_KEY_ENV_VAR = "OPENAI_KEY"
OPENAI_STANDARD_API_KEY_ENV_VAR = "OPENAI_API_KEY"
OPENAI_MODEL_ENV_VAR = "OPENAI_MODEL"
DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_MAX_OUTPUT_TOKENS = 4096

OPENROUTER_API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
OPENROUTER_MODEL_ENV_VAR = "OPENROUTER_MODEL"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash-0731"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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
    "OpenAIProvider",
    "OpenRouterProvider",
]
