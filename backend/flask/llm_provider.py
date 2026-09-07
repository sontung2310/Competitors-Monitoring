"""Reusable, environment-configured LLM provider boundary.

This module owns provider SDK construction and response validation for offline
fixture generation. It deliberately has no database or monitoring imports, so
discovery's future provider wiring can reuse it without putting an LLM in the
live monitoring path.
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
    "LLMProvider",
    "LLMProviderConfigurationError",
    "LLMProviderError",
    "LLMProviderResponseError",
    "OPENAI_API_KEY_ENV_VAR",
    "OPENAI_STANDARD_API_KEY_ENV_VAR",
    "OPENAI_MODEL_ENV_VAR",
    "OpenAIProvider",
]
