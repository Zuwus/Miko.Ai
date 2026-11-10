from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceOverview:
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    session_count: int
    file_count: int
    recent_activity: str


@dataclass(frozen=True)
class Session:
    id: str
    name: str
    summary: str
    created_at: str
    updated_at: str
    workspace_id: str | None = None


@dataclass(frozen=True)
class Message:
    id: int
    session_id: str
    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class LoadedFile:
    id: int
    session_id: str
    path: str
    name: str
    kind: str
    content: str
    summary: str
    created_at: str
    workspace_id: str | None = None


@dataclass(frozen=True)
class ActivityLog:
    id: int
    session_id: str | None
    event_type: str
    summary: str
    details: str
    created_at: str


@dataclass(frozen=True)
class JournalEntry:
    id: int
    session_id: str | None
    title: str
    content: str
    trigger_type: str
    created_at: str


@dataclass(frozen=True)
class SafeMemory:
    id: int
    session_id: str | None
    title: str
    summary: str
    importance: int
    reason: str
    created_at: str


@dataclass(frozen=True)
class MemorySearchResult:
    source_type: str
    timestamp: str
    preview: str


@dataclass(frozen=True)
class TimelineEntry:
    source_type: str
    timestamp: str
    title: str
    preview: str


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    def close(self) -> None:
        return

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(content, session_id UNINDEXED, message_id UNINDEXED);

                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS loaded_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS activity_logs_fts
                USING fts5(summary, details, event_type UNINDEXED, log_id UNINDEXED);

                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS safe_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    importance INTEGER NOT NULL CHECK(importance BETWEEN 1 AND 5),
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
                );
                """
            )
            self._ensure_column(conn, "sessions", "workspace_id", "TEXT")
            self._ensure_column(conn, "loaded_files", "workspace_id", "TEXT")
            default_workspace_id = self._ensure_default_workspace(conn)
            conn.execute(
                "UPDATE sessions SET workspace_id = ? WHERE workspace_id IS NULL OR workspace_id = ''",
                (default_workspace_id,),
            )
            conn.execute(
                """
                UPDATE loaded_files
                SET workspace_id = (
                    SELECT sessions.workspace_id
                    FROM sessions
                    WHERE sessions.id = loaded_files.session_id
                )
                WHERE workspace_id IS NULL OR workspace_id = ''
                """
            )
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {str(row["name"]) for row in rows}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_default_workspace(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE name = ? COLLATE NOCASE",
            ("Personal",),
        ).fetchone()
        if row:
            return str(row["id"])
        now = utc_now()
        workspace_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO workspaces (id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (workspace_id, "Personal", "Default workspace for existing Miko sessions.", now, now),
        )
        self._add_activity_log(
            conn,
            session_id=None,
            event_type="workspace_created",
            summary="Workspace created: Personal",
            details={"workspace_id": workspace_id, "migration": True},
        )
        return workspace_id

    def get_or_create_session(self, name: str, workspace_id: str | None = None) -> Session:
        clean_name = name.strip() or "Personal"
        with self._connect() as conn:
            target_workspace_id = workspace_id or self._ensure_default_workspace(conn)
            row = conn.execute(
                "SELECT * FROM sessions WHERE name = ? COLLATE NOCASE",
                (clean_name,),
            ).fetchone()
            if row:
                return self._session_from_row(row)

            now = utc_now()
            session_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO sessions (id, name, summary, created_at, updated_at, workspace_id)
                VALUES (?, ?, '', ?, ?, ?)
                """,
                (session_id, clean_name, now, now, target_workspace_id),
            )
            self._add_activity_log(
                conn,
                session_id=session_id,
                event_type="session_created",
                summary=f"Session created: {clean_name}",
                details={"session_name": clean_name, "workspace_id": target_workspace_id},
            )
            conn.commit()
            return Session(session_id, clean_name, "", now, now, target_workspace_id)

    def list_sessions(self) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, name COLLATE NOCASE"
            ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def list_sessions_for_workspace(self, workspace_id: str) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                WHERE workspace_id = ?
                ORDER BY updated_at DESC, name COLLATE NOCASE
                """,
                (workspace_id,),
            ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def get_or_create_workspace(self, name: str, description: str = "") -> Workspace:
        clean_name = name.strip() or "Personal"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE name = ? COLLATE NOCASE",
                (clean_name,),
            ).fetchone()
            if row:
                return self._workspace_from_row(row)
            now = utc_now()
            workspace_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO workspaces (id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (workspace_id, clean_name, description.strip(), now, now),
            )
            self._add_activity_log(
                conn,
                session_id=None,
                event_type="workspace_created",
                summary=f"Workspace created: {clean_name}",
                details={"workspace_id": workspace_id},
            )
            conn.commit()
            return Workspace(workspace_id, clean_name, description.strip(), now, now)

    def list_workspaces(self) -> list[Workspace]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workspaces ORDER BY updated_at DESC, name COLLATE NOCASE"
            ).fetchall()
        return [self._workspace_from_row(row) for row in rows]

    def workspace_overviews(self) -> list[WorkspaceOverview]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.*,
                    COUNT(DISTINCT s.id) AS session_count,
                    COUNT(DISTINCT lf.id) AS file_count,
                    COALESCE(MAX(a.created_at), w.updated_at) AS recent_activity
                FROM workspaces w
                LEFT JOIN sessions s ON s.workspace_id = w.id
                LEFT JOIN loaded_files lf ON lf.workspace_id = w.id
                LEFT JOIN activity_logs a
                    ON a.session_id = s.id
                    OR json_extract(a.details, '$.workspace_id') = w.id
                GROUP BY w.id
                ORDER BY recent_activity DESC, w.name COLLATE NOCASE
                """
            ).fetchall()
        return [self._workspace_overview_from_row(row) for row in rows]

    def rename_workspace(self, workspace_id: str, name: str, description: str) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Workspace name cannot be empty.")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workspaces
                SET name = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (clean_name, description.strip(), utc_now(), workspace_id),
            )
            self._add_activity_log(
                conn,
                session_id=None,
                event_type="workspace_updated",
                summary=f"Workspace updated: {clean_name}",
                details={"workspace_id": workspace_id},
            )
            conn.commit()

    def delete_empty_workspace(self, workspace_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM sessions WHERE workspace_id = ?) AS session_count,
                    (SELECT COUNT(*) FROM loaded_files WHERE workspace_id = ?) AS file_count,
                    (SELECT name FROM workspaces WHERE id = ?) AS name
                """,
                (workspace_id, workspace_id, workspace_id),
            ).fetchone()
            if not row or row["name"] is None:
                return False
            if int(row["session_count"]) > 0 or int(row["file_count"]) > 0:
                return False
            conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
            self._add_activity_log(
                conn,
                session_id=None,
                event_type="workspace_deleted",
                summary=f"Empty workspace deleted: {row['name']}",
                details={"workspace_id": workspace_id},
            )
            conn.commit()
            return True

    def update_session_summary(self, session_id: str, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
                (summary.strip(), utc_now(), session_id),
            )
            conn.commit()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages (session_id, role, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, json.dumps(metadata or {}), now),
            )
            message_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO messages_fts (content, session_id, message_id) VALUES (?, ?, ?)",
                (content, session_id, message_id),
            )
            if role == "user":
                self._add_activity_log(
                    conn,
                    session_id=session_id,
                    event_type="user_request",
                    summary=self._objective_request_summary(content),
                    details={"message_id": message_id},
                )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()
            return message_id

    def recent_messages(self, session_id: str, limit: int) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in reversed(rows)]

    def session_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in reversed(rows)]

    def message_count(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["count"])

    def search_messages(self, session_id: str, query: str, limit: int) -> list[Message]:
        fts_query = self._fts_query(query)
        if not fts_query:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*
                FROM messages_fts f
                JOIN messages m ON m.id = f.message_id
                WHERE f.session_id = ? AND messages_fts MATCH ?
                ORDER BY bm25(messages_fts)
                LIMIT ?
                """,
                (session_id, fts_query, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def search_workspace_messages(self, workspace_id: str, query: str, limit: int) -> list[Message]:
        fts_query = self._fts_query(query)
        if not fts_query:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*
                FROM messages_fts f
                JOIN messages m ON m.id = f.message_id
                JOIN sessions s ON s.id = m.session_id
                WHERE s.workspace_id = ? AND messages_fts MATCH ?
                ORDER BY bm25(messages_fts)
                LIMIT ?
                """,
                (workspace_id, fts_query, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def set_preference(self, key: str, value: str, source: str = "user") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (key, value, source, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (key.strip(), value.strip(), source, utc_now()),
            )
            conn.commit()

    def forget_preference(self, key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM preferences WHERE key = ?", (key.strip(),))
            conn.commit()
            return cur.rowcount > 0

    def list_preferences(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM preferences ORDER BY key COLLATE NOCASE"
            ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def add_loaded_file(self, session_id: str, path: str, name: str, kind: str, content: str) -> LoadedFile:
        now = utc_now()
        with self._connect() as conn:
            session_row = conn.execute(
                "SELECT workspace_id FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            workspace_id = str(session_row["workspace_id"]) if session_row and session_row["workspace_id"] else None
            cur = conn.execute(
                """
                INSERT INTO loaded_files (session_id, workspace_id, path, name, kind, content, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, '', ?)
                """,
                (session_id, workspace_id, path, name, kind, content, now),
            )
            file_id = int(cur.lastrowid)
            self._add_activity_log(
                conn,
                session_id=session_id,
                event_type="file_loaded",
                summary=f"File loaded: {name}",
                details={"file_id": file_id, "path": path, "kind": kind, "workspace_id": workspace_id},
            )
            conn.commit()
        return LoadedFile(file_id, session_id, path, name, kind, content, "", now, workspace_id)

    def list_loaded_files(self, session_id: str) -> list[LoadedFile]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM loaded_files WHERE session_id = ? ORDER BY id DESC",
                (session_id,),
            ).fetchall()
        return [self._loaded_file_from_row(row) for row in rows]

    def list_loaded_files_for_workspace(self, workspace_id: str, limit: int = 10) -> list[LoadedFile]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM loaded_files
                WHERE workspace_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [self._loaded_file_from_row(row) for row in rows]

    def get_loaded_file(self, session_id: str, file_id: int) -> LoadedFile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM loaded_files WHERE session_id = ? AND id = ?",
                (session_id, file_id),
            ).fetchone()
        return self._loaded_file_from_row(row) if row else None

    def update_file_summary(self, file_id: int, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE loaded_files SET summary = ? WHERE id = ?",
                (summary.strip(), file_id),
            )
            conn.commit()

    def add_activity_log(
        self,
        session_id: str | None,
        event_type: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> int:
        with self._connect() as conn:
            log_id = self._add_activity_log(conn, session_id, event_type, summary, details)
            conn.commit()
            return log_id

    def _add_activity_log(
        self,
        conn: sqlite3.Connection,
        session_id: str | None,
        event_type: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> int:
        now = utc_now()
        details_text = json.dumps(details or {}, ensure_ascii=False)
        cur = conn.execute(
            """
            INSERT INTO activity_logs (session_id, event_type, summary, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, event_type.strip(), summary.strip(), details_text, now),
        )
        log_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO activity_logs_fts (summary, details, event_type, log_id) VALUES (?, ?, ?, ?)",
            (summary.strip(), details_text, event_type.strip(), log_id),
        )
        return log_id

    def list_activity_logs(self, limit: int = 50, query: str | None = None) -> list[ActivityLog]:
        with self._connect() as conn:
            if query:
                fts_query = self._fts_query(query)
                if fts_query:
                    rows = conn.execute(
                        """
                        SELECT a.*
                        FROM activity_logs_fts f
                        JOIN activity_logs a ON a.id = f.log_id
                        WHERE activity_logs_fts MATCH ?
                        ORDER BY a.id DESC
                        LIMIT ?
                        """,
                        (fts_query, limit),
                    ).fetchall()
                    return [self._activity_log_from_row(row) for row in rows]

            rows = conn.execute(
                "SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._activity_log_from_row(row) for row in rows]

    def add_journal_entry(
        self,
        session_id: str | None,
        title: str,
        content: str,
        trigger_type: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO journal_entries (session_id, title, content, trigger_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, title.strip(), content.strip(), trigger_type.strip(), utc_now()),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_journal_entries(self, limit: int = 20) -> list[JournalEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM journal_entries ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._journal_entry_from_row(row) for row in rows]

    def add_safe_memory(
        self,
        session_id: str | None,
        title: str,
        summary: str,
        importance: int,
        reason: str,
    ) -> int:
        safe_importance = max(1, min(5, int(importance)))
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO safe_memories (session_id, title, summary, importance, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, title.strip(), summary.strip(), safe_importance, reason.strip(), utc_now()),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_safe_memories(self, limit: int = 20) -> list[SafeMemory]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM safe_memories
                ORDER BY importance DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._safe_memory_from_row(row) for row in rows]

    def recent_journal_entry_count(self, session_id: str, message_window: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM journal_entries
                WHERE session_id = ?
                  AND id >= COALESCE((SELECT MAX(id) FROM journal_entries WHERE session_id = ?), 0)
                """,
                (session_id, session_id),
            ).fetchone()
        return int(row["count"])

    def safe_memory_exists(self, title: str, summary: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM safe_memories
                WHERE lower(title) = lower(?) OR lower(summary) = lower(?)
                LIMIT 1
                """,
                (title.strip(), summary.strip()),
            ).fetchone()
        return row is not None

    def memory_search(self, query: str, source_types: set[str], limit: int = 100) -> list[MemorySearchResult]:
        clean_query = query.strip()
        if not clean_query:
            return []
        fts_query = self._fts_query(clean_query)
        like_query = f"%{clean_query}%"
        results: list[MemorySearchResult] = []
        with self._connect() as conn:
            if "messages" in source_types and fts_query:
                rows = conn.execute(
                    """
                    SELECT m.created_at, m.role || ': ' || m.content AS preview
                    FROM messages_fts f
                    JOIN messages m ON m.id = f.message_id
                    WHERE messages_fts MATCH ?
                    ORDER BY m.id DESC
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
                results.extend(MemorySearchResult("Message", str(row["created_at"]), str(row["preview"])) for row in rows)

            if "preferences" in source_types:
                rows = conn.execute(
                    """
                    SELECT updated_at, key || ': ' || value AS preview
                    FROM preferences
                    WHERE key LIKE ? OR value LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (like_query, like_query, limit),
                ).fetchall()
                results.extend(MemorySearchResult("Preference", str(row["updated_at"]), str(row["preview"])) for row in rows)

            if "logs" in source_types and fts_query:
                rows = conn.execute(
                    """
                    SELECT a.created_at, a.event_type || ': ' || a.summary AS preview
                    FROM activity_logs_fts f
                    JOIN activity_logs a ON a.id = f.log_id
                    WHERE activity_logs_fts MATCH ?
                    ORDER BY a.id DESC
                    LIMIT ?
                    """,
                    (fts_query, limit),
                ).fetchall()
                results.extend(MemorySearchResult("Activity Log", str(row["created_at"]), str(row["preview"])) for row in rows)

            if "journal" in source_types:
                rows = conn.execute(
                    """
                    SELECT created_at, title || ': ' || content AS preview
                    FROM journal_entries
                    WHERE title LIKE ? OR content LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (like_query, like_query, limit),
                ).fetchall()
                results.extend(MemorySearchResult("Journal", str(row["created_at"]), str(row["preview"])) for row in rows)

            if "safe" in source_types:
                rows = conn.execute(
                    """
                    SELECT created_at, title || ': ' || summary AS preview
                    FROM safe_memories
                    WHERE title LIKE ? OR summary LIKE ? OR reason LIKE ?
                    ORDER BY importance DESC, id DESC
                    LIMIT ?
                    """,
                    (like_query, like_query, like_query, limit),
                ).fetchall()
                results.extend(MemorySearchResult("Safe", str(row["created_at"]), str(row["preview"])) for row in rows)

        results.sort(key=lambda item: item.timestamp, reverse=True)
        return results[:limit]

    def timeline_entries(self, limit: int = 200) -> list[TimelineEntry]:
        entries: list[TimelineEntry] = []
        with self._connect() as conn:
            log_rows = conn.execute(
                """
                SELECT created_at, event_type, summary
                FROM activity_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            entries.extend(
                TimelineEntry("Activity Log", str(row["created_at"]), str(row["event_type"]), str(row["summary"]))
                for row in log_rows
            )

            journal_rows = conn.execute(
                """
                SELECT created_at, title, content
                FROM journal_entries
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            entries.extend(
                TimelineEntry("Journal", str(row["created_at"]), str(row["title"]), str(row["content"]))
                for row in journal_rows
            )

            safe_rows = conn.execute(
                """
                SELECT created_at, title, summary
                FROM safe_memories
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            entries.extend(
                TimelineEntry("Safe", str(row["created_at"]), str(row["title"]), str(row["summary"]))
                for row in safe_rows
            )

        entries.sort(key=lambda item: item.timestamp, reverse=True)
        return entries[:limit]

    @staticmethod
    def _workspace_from_row(row: sqlite3.Row) -> Workspace:
        return Workspace(
            str(row["id"]),
            str(row["name"]),
            str(row["description"]),
            str(row["created_at"]),
            str(row["updated_at"]),
        )

    @staticmethod
    def _workspace_overview_from_row(row: sqlite3.Row) -> WorkspaceOverview:
        return WorkspaceOverview(
            str(row["id"]),
            str(row["name"]),
            str(row["description"]),
            str(row["created_at"]),
            str(row["updated_at"]),
            int(row["session_count"]),
            int(row["file_count"]),
            str(row["recent_activity"]),
        )

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> Session:
        workspace_id = row["workspace_id"] if "workspace_id" in row.keys() else None
        return Session(
            str(row["id"]),
            str(row["name"]),
            str(row["summary"]),
            str(row["created_at"]),
            str(row["updated_at"]),
            str(workspace_id) if workspace_id else None,
        )

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> Message:
        return Message(int(row["id"]), str(row["session_id"]), str(row["role"]), str(row["content"]), str(row["created_at"]))

    @staticmethod
    def _loaded_file_from_row(row: sqlite3.Row) -> LoadedFile:
        return LoadedFile(
            int(row["id"]),
            str(row["session_id"]),
            str(row["path"]),
            str(row["name"]),
            str(row["kind"]),
            str(row["content"]),
            str(row["summary"]),
            str(row["created_at"]),
            str(row["workspace_id"]) if "workspace_id" in row.keys() and row["workspace_id"] else None,
        )

    @staticmethod
    def _activity_log_from_row(row: sqlite3.Row) -> ActivityLog:
        return ActivityLog(
            int(row["id"]),
            str(row["session_id"]) if row["session_id"] is not None else None,
            str(row["event_type"]),
            str(row["summary"]),
            str(row["details"]),
            str(row["created_at"]),
        )

    @staticmethod
    def _journal_entry_from_row(row: sqlite3.Row) -> JournalEntry:
        return JournalEntry(
            int(row["id"]),
            str(row["session_id"]) if row["session_id"] is not None else None,
            str(row["title"]),
            str(row["content"]),
            str(row["trigger_type"]),
            str(row["created_at"]),
        )

    @staticmethod
    def _safe_memory_from_row(row: sqlite3.Row) -> SafeMemory:
        return SafeMemory(
            int(row["id"]),
            str(row["session_id"]) if row["session_id"] is not None else None,
            str(row["title"]),
            str(row["summary"]),
            int(row["importance"]),
            str(row["reason"]),
            str(row["created_at"]),
        )

    @staticmethod
    def _objective_request_summary(content: str) -> str:
        clean = " ".join(content.split())
        if len(clean) > 140:
            clean = clean[:137] + "..."
        return f"User submitted request: {clean}"

    @staticmethod
    def _fts_query(query: str) -> str:
        terms = [part.strip() for part in query.replace('"', " ").split() if len(part.strip()) >= 3]
        return " OR ".join(f'"{term}"' for term in terms[:8])
