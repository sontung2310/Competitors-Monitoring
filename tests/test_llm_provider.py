from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from backend.flask.llm_provider import (
    LLMProviderConfigurationError,
    LLMProviderError,
    LLMProviderResponseError,
    OpenAIProvider,
    OpenRouterProvider,
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

    def test_consumer_model_override_still_uses_shared_provider(self):
        client = _FakeClient("generated fixture")
        provider = OpenAIProvider.from_env(
            {
                "OPENAI_KEY": "test-key-not-used",
                "OPENAI_MODEL": "shared-default",
            },
            model="consumer-model",
            client=client,
        )

        provider.generate("make a fixture", instructions="return fixture text")

        self.assertEqual(client.responses.calls[0]["model"], "consumer-model")

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


class _FakeChatMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChatChoice:
    def __init__(self, content: str):
        self.message = _FakeChatMessage(content)


class _FakeChatCompletions:
    def __init__(self, output: str):
        self.output = output
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[_FakeChatChoice(self.output)])


class _FakeChatClient:
    def __init__(self, output: str):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions(output))

    @property
    def completions(self):  # convenience for assertions below
        return self.chat.completions


class _FailingChatCompletions:
    def create(self, **kwargs):
        raise RuntimeError("provider unavailable")


class _FailingChatClient:
    chat = SimpleNamespace(completions=_FailingChatCompletions())


class OpenRouterProviderTests(unittest.TestCase):
    def test_provider_requires_api_key_without_injected_client(self):
        with self.assertRaisesRegex(LLMProviderConfigurationError, "OPENROUTER_API_KEY"):
            OpenRouterProvider.from_env(environ={})

    def test_provider_uses_environment_model_and_returns_text(self):
        client = _FakeChatClient("generated fixture")
        provider = OpenRouterProvider.from_env(
            {
                "OPENROUTER_API_KEY": "test-key-not-used",
                "OPENROUTER_MODEL": "deepseek/deepseek-v4-flash-0731",
            },
            client=client,
        )

        result = provider.generate(
            "make a fixture",
            instructions="return fixture text",
        )

        self.assertEqual(result, "generated fixture")
        call = client.completions.calls[0]
        self.assertEqual(call["model"], "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(
            call["messages"],
            [
                {"role": "system", "content": "return fixture text"},
                {"role": "user", "content": "make a fixture"},
            ],
        )

    def test_generate_json_translates_response_format_and_parses_output(self):
        payload = {"removed_key": "/product/one"}
        client = _FakeChatClient(json.dumps(payload))
        provider = OpenRouterProvider(
            api_key="test-key-not-used",
            client=client,
        )

        result = provider.generate_json(
            "make a plan",
            instructions="return JSON",
            response_format={
                "type": "json_schema",
                "name": "plan",
                "strict": True,
                "schema": {"type": "object"},
            },
        )

        self.assertEqual(result, payload)
        self.assertEqual(
            client.completions.calls[0]["response_format"],
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "plan",
                    "strict": True,
                    "schema": {"type": "object"},
                },
            },
        )

    def test_invalid_or_failed_provider_output_is_not_fabricated(self):
        invalid_client = _FakeChatClient("not json")
        provider = OpenRouterProvider(api_key="test-key-not-used", client=invalid_client)
        with self.assertRaises(LLMProviderResponseError):
            provider.generate_json(
                "make a plan",
                instructions="return JSON",
                response_format={"type": "json_schema", "name": "plan"},
            )

        failing_provider = OpenRouterProvider(
            api_key="test-key-not-used",
            client=_FailingChatClient(),
        )
        with self.assertRaisesRegex(LLMProviderError, "OpenRouter request failed"):
            failing_provider.generate("make a fixture", instructions="return text")


if __name__ == "__main__":
    unittest.main()
