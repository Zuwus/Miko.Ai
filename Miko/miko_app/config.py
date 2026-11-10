from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class OllamaSettings:
    host: str
    model: str
    temperature: float
    context_messages: int
    summary_every_messages: int


@dataclass(frozen=True)
class MikoSettings:
    default_session: str
    database_path: Path
    max_file_chars: int
    max_prompt_file_chars: int
    max_retrieved_messages: int


@dataclass(frozen=True)
class Settings:
    project_root: Path
    ollama: OllamaSettings
    miko: MikoSettings


def load_settings(path: Path, project_root: Path) -> Settings:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")

    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ollama_raw = raw.get("ollama", {})
    miko_raw = raw.get("miko", {})

    database_path = Path(miko_raw.get("database_path", "data/miko.db"))
    if not database_path.is_absolute():
        database_path = project_root / database_path

    return Settings(
        project_root=project_root,
        ollama=OllamaSettings(
            host=str(ollama_raw.get("host", "http://localhost:11434")),
            model=str(ollama_raw.get("model", "llama3.1:8b")),
            temperature=float(ollama_raw.get("temperature", 0.7)),
            context_messages=int(ollama_raw.get("context_messages", 12)),
            summary_every_messages=int(ollama_raw.get("summary_every_messages", 10)),
        ),
        miko=MikoSettings(
            default_session=str(miko_raw.get("default_session", "Personal")),
            database_path=database_path,
            max_file_chars=int(miko_raw.get("max_file_chars", 60000)),
            max_prompt_file_chars=int(miko_raw.get("max_prompt_file_chars", 18000)),
            max_retrieved_messages=int(miko_raw.get("max_retrieved_messages", 6)),
        ),
    )
