from __future__ import annotations

from miko_app.storage import Storage


def test_sessions_are_separate(tmp_path):
    storage = Storage(tmp_path / "miko.db")
    personal = storage.get_or_create_session("Personal")
    math = storage.get_or_create_session("Mathematics")

    storage.add_message(personal.id, "user", "I like short answers.")
    storage.add_message(math.id, "user", "Explain integrals with examples.")

    personal_messages = storage.recent_messages(personal.id, 10)
    math_messages = storage.recent_messages(math.id, 10)

    assert len(personal_messages) == 1
    assert len(math_messages) == 1
    assert "short answers" in personal_messages[0].content
    assert "integrals" in math_messages[0].content


def test_preferences_are_transparent(tmp_path):
    storage = Storage(tmp_path / "miko.db")
    storage.set_preference("preferred_name", "Alex")
    storage.set_preference("explanation_style", "casual examples first")

    assert storage.list_preferences() == {
        "explanation_style": "casual examples first",
        "preferred_name": "Alex",
    }

    assert storage.forget_preference("preferred_name") is True
    assert "preferred_name" not in storage.list_preferences()


def test_activity_logs_are_timestamped_and_searchable(tmp_path):
    storage = Storage(tmp_path / "miko.db")
    session = storage.get_or_create_session("Projects")
    storage.add_activity_log(
        session.id,
        "milestone",
        "Project milestone recorded",
        {"name": "first launch"},
    )

    logs = storage.list_activity_logs(query="milestone")

    assert logs
    assert logs[0].created_at
    assert logs[0].event_type == "milestone"


def test_journal_and_safe_are_separate(tmp_path):
    storage = Storage(tmp_path / "miko.db")
    session = storage.get_or_create_session("Personal")
    storage.add_journal_entry(session.id, "Pattern noticed", "Miko noticed a recurring study rhythm.", "test")
    storage.add_safe_memory(
        session.id,
        "First launch",
        "Miko launched successfully for the first time.",
        5,
        "This is a durable project milestone.",
    )

    journals = storage.list_journal_entries()
    safe = storage.list_safe_memories()

    assert journals[0].title == "Pattern noticed"
    assert safe[0].title == "First launch"
    assert journals[0].content != safe[0].summary


def test_workspace_migration_and_counts(tmp_path):
    storage = Storage(tmp_path / "miko.db")
    workspace = storage.get_or_create_workspace("Coding", "Code study")
    session = storage.get_or_create_session("Python", workspace.id)
    storage.add_loaded_file(session.id, "C:/notes.md", "notes.md", "md", "workspace notes")

    overviews = storage.workspace_overviews()
    coding = next(item for item in overviews if item.name == "Coding")

    assert session.workspace_id == workspace.id
    assert coding.session_count == 1
    assert coding.file_count == 1


def test_memory_search_and_timeline(tmp_path):
    storage = Storage(tmp_path / "miko.db")
    session = storage.get_or_create_session("Personal")
    storage.add_message(session.id, "user", "remember algebra practice")
    storage.set_preference("study_topic", "algebra")
    storage.add_journal_entry(session.id, "Algebra rhythm", "The user returned to algebra practice.", "test")
    storage.add_safe_memory(session.id, "Algebra milestone", "A durable algebra learning moment.", 4, "Important study progress.")

    results = storage.memory_search(
        "algebra",
        {"messages", "preferences", "logs", "journal", "safe"},
    )
    timeline = storage.timeline_entries()

    assert {result.source_type for result in results} >= {"Message", "Preference", "Journal", "Safe"}
    assert any(entry.source_type == "Safe" for entry in timeline)
