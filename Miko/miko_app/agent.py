from __future__ import annotations

import json

from miko_app.config import Settings
from miko_app.files import FileReader
from miko_app.ollama_client import OllamaClient
from miko_app.storage import (
    ActivityLog,
    JournalEntry,
    LoadedFile,
    MemorySearchResult,
    SafeMemory,
    Session,
    Storage,
    TimelineEntry,
    Workspace,
    WorkspaceOverview,
)


SYSTEM_PROMPT = """You are Miko v0.1, a friendly local-first AI companion and assistant.
You are casual, approachable, and useful without being theatrical.
You are text-only. You do not have an avatar, voice, web access, automation, code execution, or background services.
You may help the user think, write, learn, summarize loaded files, and answer questions about loaded files.
Be honest about limits. If the answer depends on current internet facts, say you cannot browse in v0.1.
Do not claim to have done anything outside this terminal app.
Keep sessions separate and use only the context supplied for the active session."""


class MainAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.miko.database_path)
        self.ollama = OllamaClient(settings.ollama)
        self.file_reader = FileReader(settings.miko.max_file_chars)

    def close(self) -> None:
        self.storage.close()

    def get_or_create_session(self, name: str | None = None, workspace_id: str | None = None) -> Session:
        return self.storage.get_or_create_session(name or self.settings.miko.default_session, workspace_id)

    def switch_session(self, name: str, workspace_id: str | None = None) -> Session:
        return self.storage.get_or_create_session(name, workspace_id)

    def list_sessions(self) -> list[Session]:
        return self.storage.list_sessions()

    def list_sessions_for_workspace(self, workspace_id: str) -> list[Session]:
        return self.storage.list_sessions_for_workspace(workspace_id)

    def get_or_create_workspace(self, name: str, description: str = "") -> Workspace:
        return self.storage.get_or_create_workspace(name, description)

    def list_workspaces(self) -> list[Workspace]:
        return self.storage.list_workspaces()

    def workspace_overviews(self) -> list[WorkspaceOverview]:
        return self.storage.workspace_overviews()

    def rename_workspace(self, workspace_id: str, name: str, description: str) -> None:
        self.storage.rename_workspace(workspace_id, name, description)

    def delete_empty_workspace(self, workspace_id: str) -> bool:
        return self.storage.delete_empty_workspace(workspace_id)

    def load_file(self, session: Session, raw_path: str) -> LoadedFile:
        result = self.file_reader.read(raw_path)
        return self.storage.add_loaded_file(
            session_id=session.id,
            path=str(result.path),
            name=result.name,
            kind=result.kind,
            content=result.content,
        )

    def list_loaded_files(self, session: Session) -> list[LoadedFile]:
        return self.storage.list_loaded_files(session.id)

    def session_messages(self, session: Session, limit: int = 50):
        return self.storage.session_messages(session.id, limit)

    def message_count(self, session: Session) -> int:
        return self.storage.message_count(session.id)

    def summarize_file_stream(self, session: Session, file_id: int | None = None):
        files = self._selected_files(session, file_id)
        if not files:
            yield "There are no loaded files in this session yet. Use `load <path>` first."
            return

        file_context = self._format_file_context(files, self.settings.miko.max_prompt_file_chars)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Summarize the loaded file content below. Include the main ideas, useful details, "
                    "and anything the user may want to ask about next.\n\n"
                    f"{file_context}"
                ),
            },
        ]
        chunks: list[str] = []
        for chunk in self.ollama.chat_stream(messages):
            chunks.append(chunk)
            yield chunk
        summary = "".join(chunks).strip()
        if file_id is not None and len(files) == 1 and summary:
            self.storage.update_file_summary(files[0].id, summary)

    def chat_stream(self, session: Session, user_text: str):
        self.storage.add_message(session.id, "user", user_text)
        prompt_messages = self._build_prompt(session, user_text)

        chunks: list[str] = []
        for chunk in self.ollama.chat_stream(prompt_messages):
            chunks.append(chunk)
            yield chunk

        assistant_text = "".join(chunks).strip()
        if assistant_text:
            self.storage.add_message(session.id, "assistant", assistant_text)
        self._maybe_refresh_summary(session)
        self._maybe_curate_memory(session)

    def preferences(self) -> dict[str, str]:
        return self.storage.list_preferences()

    def activity_logs(self, limit: int = 50, query: str | None = None) -> list[ActivityLog]:
        return self.storage.list_activity_logs(limit=limit, query=query)

    def journal_entries(self, limit: int = 20) -> list[JournalEntry]:
        return self.storage.list_journal_entries(limit=limit)

    def safe_memories(self, limit: int = 20) -> list[SafeMemory]:
        return self.storage.list_safe_memories(limit=limit)

    def memory_search(self, query: str, source_types: set[str], limit: int = 100) -> list[MemorySearchResult]:
        return self.storage.memory_search(query, source_types, limit)

    def timeline_entries(self, limit: int = 200) -> list[TimelineEntry]:
        return self.storage.timeline_entries(limit)

    def set_preference(self, key: str, value: str) -> None:
        self.storage.set_preference(key, value)

    def forget_preference(self, key: str) -> bool:
        return self.storage.forget_preference(key)

    def _build_prompt(self, session: Session, user_text: str) -> list[dict[str, str]]:
        preferences = self.storage.list_preferences()
        recent = self.storage.recent_messages(session.id, self.settings.ollama.context_messages)
        retrieved = self.storage.search_messages(
            session.id,
            user_text,
            self.settings.miko.max_retrieved_messages,
        )
        loaded_files = self.storage.list_loaded_files(session.id)
        workspace_files = (
            self.storage.list_loaded_files_for_workspace(session.workspace_id, limit=5)
            if session.workspace_id
            else []
        )

        context_parts = [f"Active session: {session.name}"]
        if session.summary:
            context_parts.append(f"Session summary:\n{session.summary}")
        if preferences:
            prefs = "\n".join(f"- {key}: {value}" for key, value in preferences.items())
            context_parts.append(f"Long-term user preferences:\n{prefs}")
        safe_memories = self.storage.list_safe_memories(limit=5)
        if safe_memories:
            safe_lines = [
                f"- {memory.title}: {memory.summary}"
                for memory in safe_memories
            ]
            context_parts.append("Protected Memory Safe entries:\n" + "\n".join(safe_lines))
        if retrieved:
            lines = [f"- {msg.role}: {msg.content[:500]}" for msg in retrieved]
            context_parts.append("Relevant previous messages from this session:\n" + "\n".join(lines))
        if session.workspace_id:
            workspace_hits = [
                msg for msg in self.storage.search_workspace_messages(
                    session.workspace_id,
                    user_text,
                    self.settings.miko.max_retrieved_messages,
                )
                if msg.session_id != session.id
            ]
            if workspace_hits:
                lines = [f"- {msg.role}: {msg.content[:500]}" for msg in workspace_hits]
                context_parts.append("Relevant messages from this workspace:\n" + "\n".join(lines))
        if loaded_files:
            context_parts.append(
                "Loaded files for this session:\n"
                + self._format_file_context(loaded_files, self.settings.miko.max_prompt_file_chars)
            )
        extra_workspace_files = [file for file in workspace_files if file.session_id != session.id]
        if extra_workspace_files:
            context_parts.append(
                "Recent files from this workspace:\n"
                + self._format_file_context(extra_workspace_files, max(4000, self.settings.miko.max_prompt_file_chars // 2))
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "\n\n".join(context_parts)},
        ]
        for msg in recent:
            if msg.role in {"user", "assistant"}:
                messages.append({"role": msg.role, "content": msg.content})
        return messages

    def _maybe_refresh_summary(self, session: Session) -> None:
        every = self.settings.ollama.summary_every_messages
        if every <= 0:
            return
        count = self.storage.message_count(session.id)
        if count < every or count % every != 0:
            return

        recent = self.storage.recent_messages(session.id, every)
        transcript = "\n".join(f"{msg.role}: {msg.content}" for msg in recent)
        messages = [
            {"role": "system", "content": "You compress chat history into a concise session summary."},
            {
                "role": "user",
                "content": (
                    "Update this session summary. Preserve durable facts, goals, decisions, and open threads. "
                    "Keep it under 250 words.\n\n"
                    f"Existing summary:\n{session.summary or '(none)'}\n\n"
                    f"Recent transcript:\n{transcript}"
                ),
            },
        ]
        try:
            summary = self.ollama.chat_once(messages, temperature=0.2)
        except Exception:
            return
        if summary:
            self.storage.update_session_summary(session.id, summary)

    def _maybe_curate_memory(self, session: Session) -> None:
        count = self.storage.message_count(session.id)
        if count < 16 or count % 16 != 0:
            return

        recent = self.storage.recent_messages(session.id, 16)
        transcript = "\n".join(f"{msg.role}: {msg.content}" for msg in recent)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Miko's private memory curator. Decide whether to write an infrequent "
                    "personality journal reflection and whether a protected Safe memory is warranted. "
                    "Return only valid JSON. Do not include markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Review this recent session slice. The journal is private reflection, not a transcript. "
                    "The Safe is only for highly important, durable memories. Be selective.\n\n"
                    "Return JSON with this exact shape:\n"
                    "{\n"
                    '  "journal": {"write": true/false, "title": "...", "content": "..."},\n'
                    '  "safe": {"write": true/false, "title": "...", "summary": "...", "importance": 1-5, "reason": "..."}\n'
                    "}\n\n"
                    f"Session name: {session.name}\n"
                    f"Existing session summary: {session.summary or '(none)'}\n\n"
                    f"Recent transcript:\n{transcript}"
                ),
            },
        ]
        try:
            raw = self.ollama.chat_once(messages, temperature=0.2)
            decision = self._parse_json_object(raw)
        except Exception:
            return

        journal = decision.get("journal", {})
        if journal.get("write") is True:
            title = str(journal.get("title", "")).strip()
            content = str(journal.get("content", "")).strip()
            if title and content and 80 <= len(content) <= 2000:
                self.storage.add_journal_entry(
                    session_id=session.id,
                    title=title[:120],
                    content=content,
                    trigger_type="periodic_reflection",
                )
                self.storage.add_activity_log(
                    session_id=session.id,
                    event_type="journal_entry_created",
                    summary=f"Journal entry created: {title[:120]}",
                    details={"trigger_type": "periodic_reflection"},
                )

        safe = decision.get("safe", {})
        if safe.get("write") is True:
            title = str(safe.get("title", "")).strip()
            summary = str(safe.get("summary", "")).strip()
            reason = str(safe.get("reason", "")).strip()
            try:
                importance = int(safe.get("importance", 3))
            except (TypeError, ValueError):
                importance = 3
            if title and summary and reason and importance >= 4 and not self.storage.safe_memory_exists(title, summary):
                self.storage.add_safe_memory(
                    session_id=session.id,
                    title=title[:120],
                    summary=summary[:900],
                    importance=importance,
                    reason=reason[:500],
                )
                self.storage.add_activity_log(
                    session_id=session.id,
                    event_type="safe_memory_created",
                    summary=f"Safe memory created: {title[:120]}",
                    details={"importance": importance},
                )

    @staticmethod
    def _parse_json_object(raw: str) -> dict:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}

    def _selected_files(self, session: Session, file_id: int | None) -> list[LoadedFile]:
        if file_id is None:
            return self.storage.list_loaded_files(session.id)
        loaded = self.storage.get_loaded_file(session.id, file_id)
        return [loaded] if loaded else []

    @staticmethod
    def _format_file_context(files: list[LoadedFile], max_chars: int) -> str:
        if not files:
            return ""
        per_file = max(1000, max_chars // max(1, len(files)))
        blocks = []
        for loaded in files:
            content = loaded.content
            if len(content) > per_file:
                content = content[:per_file] + "\n[Truncated in prompt.]"
            summary = f"\nExisting summary: {loaded.summary}" if loaded.summary else ""
            blocks.append(
                f"--- File #{loaded.id}: {loaded.name} ({loaded.kind}) ---"
                f"{summary}\nPath: {loaded.path}\nContent:\n{content}"
            )
        return "\n\n".join(blocks)
