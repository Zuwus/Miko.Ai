from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtensionRequest:
    workspace_id: str | None
    session_id: str | None
    user_text: str


@dataclass(frozen=True)
class ExtensionResult:
    summary: str
    content: str


class MikoExtension(Protocol):
    name: str

    def is_available(self) -> bool:
        ...

    def handle(self, request: ExtensionRequest) -> ExtensionResult:
        ...
