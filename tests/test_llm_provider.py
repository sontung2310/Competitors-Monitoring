from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from backend.flask.llm_provider import (
    LLMProviderConfigurationError,
    LLMProviderError,
    LLMProviderResponseError,
    OpenAIProvider,
)


class _FakeResponses:
    def __init__(self, output: str):
        self.output = output
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output)


class _FakeClient:
    def __init__(self, output: str):
        self.responses = _FakeResponses(output)


class _FailingResponses:
    def create(self, **kwargs):
        raise RuntimeError("provider unavailable")


class _FailingClient:
    responses = _FailingResponses()


class LLMProviderTests(unittest.TestCase):
    def test_provider_requires_api_key_without_injected_client(self):
        with self.assertRaisesRegex(LLMProviderConfigurationError, "OPENAI_KEY"):
            OpenAIProvider.from_env(environ={})

    def test_provider_uses_environment_model_and_returns_text(self):
        client = _FakeClient("generated fixture")
        provider = OpenAIProvider.from_env(
            {"OPENAI_KEY": "test-key-not-used", "OPENAI_MODEL": "test-model"},
            client=client,
        )

        result = provider.generate(
            "make a fixture",
            instructions="return fixture text",
        )

        self.assertEqual(result, "generated fixture")
        self.assertEqual(client.responses.calls[0]["model"], "test-model")
        self.assertEqual(client.responses.calls[0]["store"], False)

    def test_generate_json_parses_structured_output_and_sends_schema(self):
        payload = {"removed_key": "/product/one"}
        client = _FakeClient(json.dumps(payload))
        provider = OpenAIProvider(
            api_key="test-key-not-used",
            client=client,
        )

        result = provider.generate_json(
            "make a plan",
            instructions="return JSON",
            response_format={"type": "json_schema", "name": "plan"},
        )

        self.assertEqual(result, payload)
        self.assertEqual(
            client.responses.calls[0]["text"],
            {"format": {"type": "json_schema", "name": "plan"}},
        )

    def test_invalid_or_failed_provider_output_is_not_fabricated(self):
        invalid_client = _FakeClient("not json")
        provider = OpenAIProvider(api_key="test-key-not-used", client=invalid_client)
        with self.assertRaises(LLMProviderResponseError):
            provider.generate_json(
                "make a plan",
                instructions="return JSON",
                response_format={"type": "json_schema", "name": "plan"},
            )

        failing_provider = OpenAIProvider(
            api_key="test-key-not-used",
            client=_FailingClient(),
        )
        with self.assertRaisesRegex(LLMProviderError, "OpenAI request failed"):
            failing_provider.generate("make a fixture", instructions="return text")


if __name__ == "__main__":
    unittest.main()
