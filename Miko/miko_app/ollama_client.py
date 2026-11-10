from __future__ import annotations

from collections.abc import Iterable

import ollama

from miko_app.config import OllamaSettings


class OllamaUnavailable(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, settings: OllamaSettings):
        self.settings = settings
        self.client = ollama.Client(host=settings.host)

    def chat_stream(self, messages: list[dict[str, str]]) -> Iterable[str]:
        try:
            stream = self.client.chat(
                model=self.settings.model,
                messages=messages,
                stream=True,
                options={"temperature": self.settings.temperature},
            )
            for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
        except Exception as exc:
            raise OllamaUnavailable(
                f"Could not reach Ollama at {self.settings.host} using model {self.settings.model}."
            ) from exc

    def chat_once(self, messages: list[dict[str, str]], temperature: float | None = None) -> str:
        try:
            response = self.client.chat(
                model=self.settings.model,
                messages=messages,
                stream=False,
                options={"temperature": self.settings.temperature if temperature is None else temperature},
            )
            return str(response.get("message", {}).get("content", "")).strip()
        except Exception as exc:
            raise OllamaUnavailable(
                f"Could not reach Ollama at {self.settings.host} using model {self.settings.model}."
            ) from exc
