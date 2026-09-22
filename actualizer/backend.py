"""
backend.py — Pluggable model backend interface for Actualizer providers.

Ported from Arbitrator's channels/backend.py. The abstraction is generic —
"send a system prompt and a user prompt, get a string back" has nothing
to do with ethics content, hard constraints, or verdicts, so it carries
over unchanged. A referent provider never calls an API directly; it calls
backend.complete().
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class ModelBackend(ABC):
    """Abstract base class for all model backends."""

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> str:
        """
        Send a prompt to the model and return the response text.

        Raises:
            BackendError: If the model call fails for any reason.
        """

    def is_available(self) -> bool:
        """Return True if this backend is currently reachable. Default True."""
        return True

    @property
    def model_id(self) -> str:
        """A string identifying this backend and model for audit logging."""
        return "unknown"


# ---------------------------------------------------------------------------
# Anthropic API backend
# ---------------------------------------------------------------------------

class AnthropicBackend(ModelBackend):
    """
    Backend that calls the Anthropic Messages API.

    Requires the ANTHROPIC_API_KEY environment variable, or an explicit
    api_key argument.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        timeout: int = 60,
    ):
        self._model = model
        self._timeout = timeout
        self._api_key = api_key

    @property
    def model_id(self) -> str:
        return f"anthropic/{self._model}"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> str:
        import urllib.request
        import os

        api_key = self._api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise BackendError("ANTHROPIC_API_KEY not set and no api_key provided.")

        payload = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["content"][0]["text"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise BackendError(f"Anthropic API error {e.code}: {body[:500]}") from e
        except Exception as e:
            raise BackendError(f"Anthropic backend failed: {type(e).__name__}: {e}") from e

    def is_available(self) -> bool:
        import os
        return bool(self._api_key or os.environ.get("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# Ollama backend (local models)
# ---------------------------------------------------------------------------

class OllamaBackend(ModelBackend):
    """
    Backend that calls a local Ollama server (OpenAI-compatible API).
    Default URL: http://localhost:11434
    """

    def __init__(
        self,
        model: str = "mistral",
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def model_id(self) -> str:
        return f"ollama/{self._model}"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> str:
        import urllib.request

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["message"]["content"]
        except Exception as e:
            raise BackendError(f"Ollama backend failed: {type(e).__name__}: {e}") from e

    def is_available(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"{self._base_url}/api/tags", timeout=3
            ) as resp:
                return resp.status == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# LM Studio backend (local models via LM Studio's OpenAI-compatible server)
# ---------------------------------------------------------------------------

class LMStudioBackend(ModelBackend):
    """
    Backend that calls a local LM Studio server's OpenAI-compatible API.

    Start the server and load a model first (`lms server start`,
    `lms load <model> --identifier <id>`), then point this at the same
    identifier. Default URL: http://localhost:1234

    Note on gpt-oss models specifically: their raw output includes
    Harmony-format channel markers (`<|channel|>analysis<|message|>...`)
    showing the model's reasoning before its final answer. This backend
    passes that through unmodified rather than stripping it — for
    Actualizer's deliberation use case, seeing the reasoning channel is
    more honest than silently discarding it for a cleaner-looking string.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:1234",
        timeout: int = 900,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def model_id(self) -> str:
        return f"lmstudio/{self._model}"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> str:
        import urllib.request

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        req = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise BackendError(f"LM Studio backend failed: {type(e).__name__}: {e}") from e

    def is_available(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                f"{self._base_url}/v1/models", timeout=3
            ) as resp:
                return resp.status == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Mock backend (deterministic, for testing and development)
# ---------------------------------------------------------------------------

@dataclass
class MockResponse:
    """A canned response for a specific provider in the mock backend."""
    provider_name: str
    response_json: dict

    def to_json_string(self) -> str:
        return json.dumps(self.response_json)


class MockBackend(ModelBackend):
    """
    Deterministic mock backend for testing and offline development.

    Returns pre-configured JSON responses keyed by provider name, read
    from the "PROVIDER:" marker convention in the system prompt (same
    convention Arbitrator's MockBackend uses for "CHANNEL:").
    """

    def __init__(self):
        self._responses: dict[str, dict] = {}
        self._call_log: list[dict] = []

    @property
    def model_id(self) -> str:
        return "mock/deterministic-v1"

    def add_response(self, provider_name: str, response_dict: dict) -> None:
        self._responses[provider_name] = response_dict

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.3,
    ) -> str:
        provider_name = "unknown"
        for line in system_prompt.splitlines():
            if "PROVIDER:" in line:
                provider_name = line.split("PROVIDER:")[-1].strip().lower()
                break

        self._call_log.append({
            "provider": provider_name,
            "user_prompt_length": len(user_prompt),
        })

        if provider_name in self._responses:
            return json.dumps(self._responses[provider_name])

        return json.dumps(_default_mock_response(provider_name))

    @property
    def call_log(self) -> list[dict]:
        return list(self._call_log)

    def reset(self) -> None:
        self._responses.clear()
        self._call_log.clear()


def _default_mock_response(provider_name: str) -> dict:
    """Minimal valid mock response for a provider that has none registered."""
    return {
        "framing_note": (
            f"[Mock {provider_name} response] This is a placeholder. In production, "
            f"a real model would surface grounded referents for this decision."
        ),
        "confidence": 0.4,
        "referents": [
            {
                "summary": f"Mock referent from {provider_name}.",
                "detail": "This is a mock referent produced by the test backend.",
                "kind": "open_question",
                "weight": "low",
                "sources": [],
                "tags": [provider_name],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Backend registry and selection
# ---------------------------------------------------------------------------

def get_default_backend() -> ModelBackend:
    """
    Return the best available backend, in priority order:
    1. AnthropicBackend (if ANTHROPIC_API_KEY is set)
    2. OllamaBackend (if localhost:11434 is reachable)
    3. MockBackend (always available, for development)
    """
    anthropic = AnthropicBackend()
    if anthropic.is_available():
        return anthropic

    ollama = OllamaBackend()
    if ollama.is_available():
        return ollama

    return MockBackend()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class BackendError(Exception):
    """Raised when a model backend fails to produce a response."""
    pass
