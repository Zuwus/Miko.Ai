from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from miko_app.agent import MainAgent
from miko_app.config import Settings, load_settings
from miko_app.files import FileReadError
from miko_app.ollama_client import OllamaUnavailable
from miko_app.storage import Session, Workspace


PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


@st.cache_resource
def get_settings() -> Settings:
    return load_settings(SETTINGS_PATH, PROJECT_ROOT)


def get_agent() -> MainAgent:
    if "agent" not in st.session_state:
        st.session_state.agent = MainAgent(get_settings())
    return st.session_state.agent


def ensure_state(agent: MainAgent) -> None:
    if "page" not in st.session_state:
        st.session_state.page = "Chat"
    if "workspace_id" not in st.session_state:
        workspaces = agent.list_workspaces()
        workspace = workspaces[0] if workspaces else agent.get_or_create_workspace("Personal")
        st.session_state.workspace_id = workspace.id
        st.session_state.workspace_name = workspace.name
    if "session_name" not in st.session_state:
        st.session_state.session_name = get_settings().miko.default_session
    if "active_session" not in st.session_state:
        st.session_state.active_session = agent.get_or_create_session(
            st.session_state.session_name,
            st.session_state.workspace_id,
        )


def current_session(agent: MainAgent) -> Session:
    session = st.session_state.active_session
    if not isinstance(session, Session):
        session = agent.get_or_create_session(st.session_state.session_name)
        st.session_state.active_session = session
    return session


def switch_session(agent: MainAgent, name: str) -> None:
    st.session_state.session_name = name
    st.session_state.active_session = agent.switch_session(name, st.session_state.workspace_id)
    st.session_state.page = "Chat"


def switch_workspace(agent: MainAgent, workspace: Workspace) -> None:
    st.session_state.workspace_id = workspace.id
    st.session_state.workspace_name = workspace.name
    sessions = agent.list_sessions_for_workspace(workspace.id)
    if sessions:
        st.session_state.session_name = sessions[0].name
        st.session_state.active_session = sessions[0]
    else:
        st.session_state.session_name = f"{workspace.name} Session"
        st.session_state.active_session = agent.get_or_create_session(
            st.session_state.session_name,
            workspace.id,
        )
    st.session_state.page = "Chat"


def render_sidebar(agent: MainAgent) -> None:
    st.sidebar.title("Miko")

    workspaces = agent.list_workspaces()
    workspace_names = [workspace.name for workspace in workspaces]
    active_workspace = next(
        (workspace for workspace in workspaces if workspace.id == st.session_state.workspace_id),
        workspaces[0] if workspaces else agent.get_or_create_workspace("Personal"),
    )
    selected_workspace_name = st.sidebar.selectbox(
        "Workspace",
        workspace_names,
        index=workspace_names.index(active_workspace.name),
    )
    if selected_workspace_name != active_workspace.name:
        selected_workspace = next(workspace for workspace in workspaces if workspace.name == selected_workspace_name)
        switch_workspace(agent, selected_workspace)
        st.rerun()

    sessions = agent.list_sessions_for_workspace(st.session_state.workspace_id)
    names = [session.name for session in sessions]
    if st.session_state.session_name not in names:
        names.insert(0, st.session_state.session_name)

    selected = st.sidebar.selectbox(
        "Sessions",
        names,
        index=names.index(st.session_state.session_name),
    )
    if selected != st.session_state.session_name:
        switch_session(agent, selected)
        st.rerun()

    with st.sidebar.form("new_session_form", clear_on_submit=True):
        new_name = st.text_input("New session name")
        submitted = st.form_submit_button("New Session")
        if submitted and new_name.strip():
            switch_session(agent, new_name.strip())
            st.rerun()

    st.sidebar.divider()
    for page in ("Chat", "Workspace", "Memory Search", "Timeline", "Memory", "Journal", "Safe", "Settings"):
        if st.sidebar.button(page, use_container_width=True):
            st.session_state.page = page
            st.rerun()


def render_chat(agent: MainAgent) -> None:
    session = current_session(agent)
    st.title(f"Miko - {st.session_state.workspace_name} / {session.name}")

    messages = agent.session_messages(session, limit=200)
    for message in messages:
        role = "assistant" if message.role == "assistant" else "user"
        with st.chat_message(role):
            st.markdown(message.content)

    pending = st.session_state.get("pending_attachment")
    if pending:
        left, right = st.columns([0.82, 0.18])
        with left:
            st.caption(f"Attached: {pending['name']}")
        with right:
            if st.button("Remove", key="remove_attachment", use_container_width=True):
                st.session_state.pending_attachment = None
                st.session_state.attachment_uploader_key = st.session_state.get("attachment_uploader_key", 0) + 1
                st.rerun()

    st.caption("Composer")
    attach_col, input_col = st.columns([0.16, 0.84], vertical_alignment="bottom")
    with attach_col:
        uploader_key = f"attachment_uploader_{st.session_state.get('attachment_uploader_key', 0)}"
        uploaded = st.file_uploader(
            "Paperclip attachment",
            type=["pdf", "txt", "md"],
            label_visibility="visible",
            key=uploader_key,
        )
    if uploaded is not None:
        st.session_state.pending_attachment = {
            "name": uploaded.name,
            "bytes": uploaded.getvalue(),
            "suffix": Path(uploaded.name).suffix.lower(),
        }
        st.rerun()

    prompt = st.chat_input("Talk to Miko")
    if prompt:
        attachment = st.session_state.get("pending_attachment")
        display_prompt = prompt
        model_prompt = prompt
        if attachment:
            try:
                loaded = load_pending_attachment(agent, session, attachment)
            except FileReadError as exc:
                st.error(str(exc))
                return
            display_prompt = f"{prompt}\n\nAttached file: {attachment['name']}"
            model_prompt = (
                f"{prompt}\n\n"
                f"I attached and loaded file #{loaded.id}: {attachment['name']}. "
                "Please use it as context for this message."
            )
            st.session_state.pending_attachment = None
            st.session_state.attachment_uploader_key = st.session_state.get("attachment_uploader_key", 0) + 1

        with st.chat_message("user"):
            st.markdown(display_prompt)
        with st.chat_message("assistant"):
            placeholder = st.empty()
            collected: list[str] = []
            try:
                for chunk in agent.chat_stream(session, model_prompt):
                    collected.append(chunk)
                    placeholder.markdown("".join(collected))
            except OllamaUnavailable as exc:
                placeholder.error(str(exc))
            except Exception as exc:
                placeholder.error(f"Miko hit an unexpected error: {exc}")
        st.rerun()


def load_pending_attachment(agent: MainAgent, session: Session, attachment: dict) -> object:
    upload_dir = PROJECT_ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = str(attachment.get("suffix") or Path(attachment["name"]).suffix.lower())
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix,
        prefix="miko_upload_",
        dir=upload_dir,
    ) as temp_file:
        temp_file.write(attachment["bytes"])
        temp_path = Path(temp_file.name)
    return agent.load_file(session, str(temp_path))


def render_memory(agent: MainAgent) -> None:
    st.title("Memory")
    prefs = agent.preferences()
    if prefs:
        st.subheader("Long-Term Preferences")
        st.table([{"Key": key, "Value": value} for key, value in prefs.items()])
    else:
        st.info("No long-term preferences saved yet.")

    st.subheader("Add Preference")
    with st.form("add_preference", clear_on_submit=True):
        key = st.text_input("Key")
        value = st.text_input("Value")
        if st.form_submit_button("Save Preference") and key.strip() and value.strip():
            agent.set_preference(key.strip(), value.strip())
            st.success("Preference saved.")
            st.rerun()

    st.subheader("Remove Preference")
    if prefs:
        remove_key = st.selectbox("Preference", list(prefs.keys()))
        if st.button("Remove Preference"):
            agent.forget_preference(remove_key)
            st.success("Preference removed.")
            st.rerun()


def render_workspace(agent: MainAgent) -> None:
    st.title("Workspace")
    overviews = agent.workspace_overviews()
    if not overviews:
        st.info("No workspaces yet.")
    else:
        for overview in overviews:
            with st.expander(f"{overview.name} - {overview.session_count} sessions, {overview.file_count} files"):
                st.write(overview.description or "No description.")
                st.caption(f"Recent activity: {overview.recent_activity}")

    st.subheader("Create Workspace")
    with st.form("create_workspace", clear_on_submit=True):
        name = st.text_input("Name")
        description = st.text_area("Description")
        if st.form_submit_button("Create") and name.strip():
            workspace = agent.get_or_create_workspace(name.strip(), description.strip())
            switch_workspace(agent, workspace)
            st.success("Workspace created.")
            st.rerun()

    workspaces = agent.list_workspaces()
    if not workspaces:
        return

    selected = st.selectbox("Manage Workspace", workspaces, format_func=lambda workspace: workspace.name)
    st.subheader("Rename Workspace")
    with st.form("rename_workspace"):
        new_name = st.text_input("New name", value=selected.name)
        new_description = st.text_area("New description", value=selected.description)
        if st.form_submit_button("Save Changes"):
            try:
                agent.rename_workspace(selected.id, new_name, new_description)
            except ValueError as exc:
                st.error(str(exc))
            else:
                if selected.id == st.session_state.workspace_id:
                    st.session_state.workspace_name = new_name.strip()
                st.success("Workspace updated.")
                st.rerun()

    st.subheader("Delete Empty Workspace")
    st.caption("Only workspaces with zero sessions and zero files can be deleted.")
    if st.button("Delete Selected Empty Workspace"):
        if agent.delete_empty_workspace(selected.id):
            remaining = agent.list_workspaces()
            if remaining:
                switch_workspace(agent, remaining[0])
            st.success("Workspace deleted.")
            st.rerun()
        else:
            st.warning("That workspace is not empty, or it no longer exists.")


def render_memory_search(agent: MainAgent) -> None:
    st.title("Memory Search")
    query = st.text_input("Search what Miko remembers")
    selected_sources = st.multiselect(
        "Sources",
        ["Messages", "Preferences", "Logs", "Journal", "Safe"],
        default=["Messages", "Preferences", "Logs", "Journal", "Safe"],
    )
    source_map = {
        "Messages": "messages",
        "Preferences": "preferences",
        "Logs": "logs",
        "Journal": "journal",
        "Safe": "safe",
    }
    if query.strip():
        results = agent.memory_search(
            query,
            {source_map[source] for source in selected_sources},
            limit=100,
        )
        if not results:
            st.info("No memory results found.")
            return
        for result in results:
            with st.container(border=True):
                st.caption(f"{result.source_type} - {result.timestamp}")
                st.write(result.preview[:1000])


def render_timeline(agent: MainAgent) -> None:
    st.title("Timeline")
    entries = agent.timeline_entries(limit=200)
    if not entries:
        st.info("No timeline entries yet.")
        return
    chronological = st.toggle("Oldest first", value=False)
    if chronological:
        entries = list(reversed(entries))
    for entry in entries:
        with st.container(border=True):
            st.caption(f"{entry.timestamp} - {entry.source_type}")
            st.subheader(entry.title)
            st.write(entry.preview[:1000])


def render_journal(agent: MainAgent) -> None:
    st.title("Personality Journal")
    entries = agent.journal_entries(limit=50)
    if not entries:
        st.info("Miko has not written any journal reflections yet.")
        return
    for entry in entries:
        with st.expander(f"{entry.title} - {entry.created_at}"):
            st.write(entry.content)


def render_safe(agent: MainAgent) -> None:
    st.title("Memory Safe")
    memories = agent.safe_memories(limit=50)
    if not memories:
        st.info("The Memory Safe is empty right now.")
        return
    for memory in memories:
        with st.expander(f"{memory.title} - importance {memory.importance}/5"):
            st.write(memory.summary)
            st.caption(f"Reason preserved: {memory.reason}")


def render_settings() -> None:
    settings = get_settings()
    st.title("Settings")
    st.subheader("Ollama")
    st.write(f"Model: `{settings.ollama.model}`")
    st.write(f"Host: `{settings.ollama.host}`")
    st.write(f"Temperature: `{settings.ollama.temperature}`")
    st.caption("More settings controls can be added here later.")


def main() -> None:
    st.set_page_config(page_title="Miko", page_icon="M", layout="wide")
    agent = get_agent()
    ensure_state(agent)
    render_sidebar(agent)

    page = st.session_state.page
    if page == "Workspace":
        render_workspace(agent)
    elif page == "Memory Search":
        render_memory_search(agent)
    elif page == "Timeline":
        render_timeline(agent)
    elif page == "Memory":
        render_memory(agent)
    elif page == "Journal":
        render_journal(agent)
    elif page == "Safe":
        render_safe(agent)
    elif page == "Settings":
        render_settings()
    else:
        render_chat(agent)


if __name__ == "__main__":
    main()
