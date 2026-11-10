# Miko v0.1

Miko is a local-first, text-only AI companion for Windows 10. This v0.1 build focuses on the smallest useful system: terminal chat, Ollama streaming, SQLite sessions, simple memory, and local file reading for `.txt`, `.md`, and `.pdf`.

## What v0.1 Includes

- Terminal interface with `miko >`
- Ollama chat backend with streaming responses
- Configurable model in `config/settings.yaml`
- SQLite session storage in `data/miko.db`
- Multiple named sessions with separate history and loaded files
- Session summaries and simple context retrieval
- Long-term preferences stored transparently in SQLite
- File loading for readable text, code, data, document, and spreadsheet files
- File summarization and questions about loaded files

## What v0.1 Intentionally Excludes

No web agent, internet access, journal, Memory Safe, recovery system, multi-profile support, automation, code execution, file deletion, file movement, background service, startup service, voice, avatar, or separate Local/Web agents.

## Folder Structure

```text
miko-v0.1/
├── config/
│   └── settings.yaml
├── data/
│   └── .gitkeep
├── miko_app/
│   ├── __init__.py
│   ├── agent.py
│   ├── cli.py
│   ├── config.py
│   ├── files.py
│   ├── ollama_client.py
│   └── storage.py
├── tests/
│   └── test_storage.py
├── miko.py
├── README.md
└── requirements.txt
```

## Setup

1. Install Python 3.11 or newer.
2. Install Ollama from [https://ollama.com](https://ollama.com).
3. Pull a local model:

```powershell
ollama pull llama3.1:8b
```

4. Create a virtual environment and install dependencies:

```powershell
cd "C:\Users\LENOVO\Documents\New project"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

5. If you want a different model, edit:

```text
config/settings.yaml
```

## Run Streamlit UI

The Streamlit interface is the primary UI:

```powershell
cd "C:\Users\LENOVO\Documents\New project"
.\start_miko_ui.bat
```

Or manually:

```powershell
cd "C:\Users\LENOVO\Documents\New project"
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

## Run CLI Fallback

```powershell
python miko.py
```

Start CLI in a named session:

```powershell
python miko.py --session Mathematics
```

## Commands

```text
help                         Show commands
sessions                     List sessions
switch <name>                Switch or create a session
load <path>                  Load a readable file into the current session
summarize                    Summarize loaded files in the current session
summarize <file number>      Summarize one loaded file
history                      Show the latest 30 saved messages
history <number>             Show more saved messages from this session
logs                         View recent objective activity logs
logs <search>                Search activity logs
journal                      View Miko's private reflections
safe                         View protected Memory Safe entries
memory                       Show long-term preferences
memory set <key> <value>     Save or update a preference
memory forget <key>          Delete a preference
exit                         Leave Miko
```

You can also chat normally. If files are loaded, Miko can answer questions about them in the current session.

## Streamlit Pages

- Chat: conversation history, streaming replies, and PDF/TXT/MD upload.
- Workspace: create, rename, inspect, and delete empty workspaces.
- Memory Search: inspect remembered messages, preferences, logs, journal entries, and Safe memories.
- Timeline: read-only chronological view of logs, journal entries, and Safe memories.
- Memory: view, add, and remove long-term preferences.
- Journal: read-only view of Miko's private reflections.
- Safe: read-only view of protected Memory Safe entries.
- Settings: displays current Ollama model, host, and temperature.

The Streamlit UI and CLI both use the same `data/miko.db` SQLite database and the same Ollama configuration.

## Workspaces

Workspaces organize sessions, uploaded files, notes, and future knowledge by subject. Existing sessions are safely assigned to the default `Personal` workspace during startup migration.

Examples:

```text
Personal
Coding
Math
```

Sessions and loaded files belong to a workspace. In chat, Miko prioritizes the active session first, then relevant files and messages from the active workspace.

## File Reading

Miko can read common text/code/data files, plus `.pdf`, `.docx`, `.xlsx`, `.csv`, and `.tsv`.

Miko will refuse raw binary, media, archive, and executable files such as `.exe`, `.dll`, `.zip`, `.png`, `.jpg`, `.mp4`, and similar formats. That is intentional: v0.1 is read-only and text-focused.

## Chat Length

Miko stores conversation history in SQLite, so chats are saved locally beyond the PowerShell window scrollback. Use:

```text
history
history 100
```

The model still has a finite context window for each reply, so Miko uses recent messages, session summaries, and relevant saved messages instead of stuffing the entire database into every prompt.

## Additional Memory Layers

Miko keeps the original SQLite session memory and adds three separate SQLite-backed layers:

- Activity Logs: objective timestamped records for session creation, file loading, user requests, journal creation, and Safe creation.
- Personality Journal: Miko-owned private reflections generated infrequently by the local model.
- Memory Safe: Miko-owned protected memories for highly important durable milestones.

You can view these with `logs`, `journal`, and `safe`, but v0.1 does not provide manual commands to write or delete Journal/Safe entries. Miko decides what belongs there.
