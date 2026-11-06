"""AI provider abstraction. All calls are made from the backend; keys never reach the browser."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
import httpx

from ..config import get_settings


class ProviderError(Exception):
    """An AI provider failed. The message is safe to show and contains no key material."""


@dataclass
class ProviderResult:
    data: dict
    usage: dict = field(default_factory=dict)


class AIProvider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict) -> ProviderResult: ...


def _parse_json(text: str) -> dict:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProviderError("The AI provider returned a response that was not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ProviderError("The AI provider returned an unexpected response shape.")
    return value


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float, http_client=None):
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1, http_client=http_client)

    def complete_json(self, system: str, user: str, schema: dict) -> ProviderResult:
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=8000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderError("The Anthropic API key was rejected.") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("The Anthropic API rate limit was reached. Try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"The Anthropic API returned an error (status {exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("The Anthropic API could not be reached or timed out.") from exc
        if response.stop_reason == "refusal":
            raise ProviderError("The AI model declined this request.")
        if response.stop_reason == "max_tokens":
            raise ProviderError("The AI response was too long and was cut off.")
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        return ProviderResult(_parse_json(text), usage)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float, http_client: httpx.Client | None = None):
        self.model = model
        self._key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)

    def complete_json(self, system: str, user: str, schema: dict) -> ProviderResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
        }
        try:
            response = self._client.post("https://api.openai.com/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise ProviderError("The OpenAI API could not be reached or timed out.") from exc
        if response.status_code >= 400:
            raise ProviderError(f"The OpenAI API returned an error (status {response.status_code}).")
        payload = response.json()
        usage = payload.get("usage", {})
        return ProviderResult(_parse_json(payload["choices"][0]["message"]["content"]),
                              {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")})


def _gemini_schema(schema):
    """Gemini's schema dialect uses `nullable` rather than type arrays and rejects additionalProperties."""
    if isinstance(schema, list):
        return [_gemini_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, list):
            kinds = [v for v in value if v != "null"]
            result["type"] = kinds[0] if kinds else "string"
            if "null" in value:
                result["nullable"] = True
        elif key == "anyOf":
            options = [o for o in value if o.get("type") != "null"]
            result.update(_gemini_schema(options[0]))
            if len(options) != len(value):
                result["nullable"] = True
        else:
            result[key] = _gemini_schema(value) if isinstance(value, (dict, list)) else value
    return result


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float, http_client: httpx.Client | None = None):
        self.model = model
        self._key = api_key
        self._client = http_client or httpx.Client(timeout=timeout)

    def complete_json(self, system: str, user: str, schema: dict) -> ProviderResult:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": _gemini_schema(schema)},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        try:
            # The key travels in a header, so it cannot appear in logged URLs.
            response = self._client.post(url, json=body, headers={"x-goog-api-key": self._key})
        except httpx.HTTPError as exc:
            raise ProviderError("The Gemini API could not be reached or timed out.") from exc
        if response.status_code >= 400:
            raise ProviderError(f"The Gemini API returned an error (status {response.status_code}).")
        payload = response.json()
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError("The Gemini API returned no content.") from exc
        usage = payload.get("usageMetadata", {})
        return ProviderResult(_parse_json(text), {"input_tokens": usage.get("promptTokenCount"), "output_tokens": usage.get("candidatesTokenCount")})


def configured_provider_name() -> tuple[str | None, str | None]:
    """Return (provider, configuration problem). A provider of None means demonstration mode."""
    settings = get_settings()
    choice = settings.ai_provider.lower()
    if choice == "demo":
        return None, None
    keys = {
        "anthropic": (settings.anthropic_api_key, settings.anthropic_model),
        "openai": (settings.openai_api_key, settings.openai_model),
        "gemini": (settings.gemini_api_key, settings.gemini_model),
    }
    if choice == "auto":
        for name, (key, _model) in keys.items():
            if key:
                choice = name
                break
        else:
            return None, None
    if choice not in keys:
        return None, f"AI_PROVIDER '{choice}' is not recognised."
    key, model = keys[choice]
    if not key:
        return None, f"AI_PROVIDER is {choice}, but its API key is not set."
    if not model:
        return None, f"AI_PROVIDER is {choice}, but {choice.upper()}_MODEL is not set."
    return choice, None


def get_provider() -> AIProvider | None:
    settings = get_settings()
    name, _problem = configured_provider_name()
    if name == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model, settings.ai_timeout_seconds)
    if name == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.ai_timeout_seconds)
    if name == "gemini":
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds)
    return None


def ai_status() -> dict:
    settings = get_settings()
    name, problem = configured_provider_name()
    model = {"anthropic": settings.anthropic_model, "openai": settings.openai_model, "gemini": settings.gemini_model}.get(name or "")
    return {
        "mode": "live" if name else "demonstration",
        "provider": name,
        "model": model if name else None,
        "problem": problem,
        "shares_category_values": settings.ai_share_category_values if name else False,
        "external_processing": bool(name),
    }
