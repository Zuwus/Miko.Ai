from __future__ import annotations

import shlex
from collections.abc import Iterable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from miko_app.agent import MainAgent
from miko_app.config import Settings
from miko_app.files import FileReadError
from miko_app.ollama_client import OllamaUnavailable
from miko_app.storage import Session


class MikoCli:
    def __init__(self, settings: Settings, initial_session: str | None = None):
        self.console = Console()
        self.agent = MainAgent(settings)
        self.session = self.agent.get_or_create_session(initial_session)

    def run(self) -> None:
        self._show_header()
        try:
            while True:
                try:
                    text = self.console.input("[bold cyan]miko > [/]").strip()
                except (EOFError, KeyboardInterrupt):
                    self.console.print("\n[cyan]Miko:[/] Bye. I'll keep the session history here locally.")
                    return

                if not text:
                    continue
                if self._handle_command(text):
                    continue
                self._chat(text)
        finally:
            self.agent.close()

    def _show_header(self) -> None:
        self.console.print(
            Panel(
                f"[bold]Miko v0.1[/]\nSession: [cyan]{self.session.name}[/]\n"
                "Local terminal companion. Type [bold]help[/] for commands.",
                title="hello",
                border_style="cyan",
            )
        )

    def _handle_command(self, text: str) -> bool:
        normalized = text[1:] if text.startswith("/") else text
        try:
            parts = [self._clean_arg(part) for part in shlex.split(normalized, posix=False)]
        except ValueError as exc:
            self.console.print(f"[red]I couldn't parse that command:[/] {exc}")
            return True

        if not parts:
            return True
        command = parts[0].lower()
        args = parts[1:]

        if command in {"help", "h", "?"}:
            self._help()
            return True
        if command in {"exit", "quit", "q"}:
            self.console.print("[cyan]Miko:[/] Bye. I saved this session locally.")
            raise SystemExit(0)
        if command == "sessions":
            self._sessions()
            return True
        if command == "switch":
            self._switch(args)
            return True
        if command == "load":
            self._load(args)
            return True
        if command == "summarize":
            self._summarize(args)
            return True
        if command == "memory":
            self._memory(args)
            return True
        if command == "history":
            self._history(args)
            return True
        if command == "logs":
            self._logs(args)
            return True
        if command == "journal":
            self._journal(args)
            return True
        if command == "safe":
            self._safe(args)
            return True

        return False

    def _help(self) -> None:
        table = Table(title="Commands", show_header=True, header_style="bold cyan")
        table.add_column("Command", style="bold")
        table.add_column("Use")
        rows = [
            ("help", "Show this help"),
            ("sessions", "List named sessions"),
            ("switch <name>", "Switch to or create a session"),
            ("load <path>", "Load a readable text, code, document, or spreadsheet file"),
            ("summarize", "Summarize all loaded files in this session"),
            ("summarize <file number>", "Summarize one loaded file"),
            ("history", "Show the latest 30 saved messages"),
            ("history <number>", "Show more saved messages from this session"),
            ("logs", "View recent objective activity logs"),
            ("logs <search>", "Search activity logs"),
            ("journal", "View Miko's private reflections"),
            ("safe", "View protected Memory Safe entries"),
            ("memory", "Show long-term preferences"),
            ("memory set <key> <value>", "Save or update a preference"),
            ("memory forget <key>", "Delete a preference"),
            ("exit", "Leave Miko"),
        ]
        for command, use in rows:
            table.add_row(command, use)
        self.console.print(table)

    def _sessions(self) -> None:
        sessions = self.agent.list_sessions()
        table = Table(title="Sessions", show_header=True, header_style="bold cyan")
        table.add_column("Name")
        table.add_column("Updated")
        table.add_column("Summary")
        for session in sessions:
            marker = " *" if session.id == self.session.id else ""
            table.add_row(session.name + marker, session.updated_at, session.summary[:90])
        self.console.print(table)

    def _switch(self, args: list[str]) -> None:
        if not args:
            self.console.print("[yellow]Use:[/] switch <session name>")
            return
        name = " ".join(args)
        self.session = self.agent.switch_session(name)
        self.console.print(f"[cyan]Miko:[/] Switched to [bold]{self.session.name}[/].")

    def _load(self, args: list[str]) -> None:
        if not args:
            self.console.print("[yellow]Use:[/] load <path>")
            return
        path = " ".join(args)
        try:
            loaded = self.agent.load_file(self.session, path)
        except FileReadError as exc:
            self.console.print(f"[red]Miko:[/] {exc}")
            return
        self.console.print(
            f"[cyan]Miko:[/] Loaded [bold]{loaded.name}[/] as file #{loaded.id} "
            f"for the [bold]{self.session.name}[/] session."
        )

    def _summarize(self, args: list[str]) -> None:
        file_id = None
        if args:
            try:
                file_id = int(args[0])
            except ValueError:
                self.console.print("[yellow]Use:[/] summarize or summarize <file number>")
                return
        self._print_stream(self.agent.summarize_file_stream(self.session, file_id))

    def _memory(self, args: list[str]) -> None:
        if not args:
            prefs = self.agent.preferences()
            if not prefs:
                self.console.print("[cyan]Miko:[/] No long-term preferences saved yet.")
                return
            table = Table(title="Long-Term Preferences", show_header=True, header_style="bold cyan")
            table.add_column("Key")
            table.add_column("Value")
            for key, value in prefs.items():
                table.add_row(key, value)
            self.console.print(table)
            return

        action = args[0].lower()
        if action == "set" and len(args) >= 3:
            key = args[1]
            value = " ".join(args[2:])
            self.agent.set_preference(key, value)
            self.console.print(f"[cyan]Miko:[/] Saved preference [bold]{key}[/].")
            return
        if action == "forget" and len(args) == 2:
            removed = self.agent.forget_preference(args[1])
            if removed:
                self.console.print(f"[cyan]Miko:[/] Forgot preference [bold]{args[1]}[/].")
            else:
                self.console.print("[yellow]Miko:[/] I couldn't find that preference.")
            return

        self.console.print("[yellow]Use:[/] memory, memory set <key> <value>, or memory forget <key>")

    def _history(self, args: list[str]) -> None:
        limit = 30
        if args:
            try:
                limit = max(1, min(500, int(args[0])))
            except ValueError:
                self.console.print("[yellow]Use:[/] history or history <number>")
                return
        messages = self.agent.session_messages(self.session, limit)
        total = self.agent.message_count(self.session)
        if not messages:
            self.console.print("[cyan]Miko:[/] No saved messages in this session yet.")
            return
        self.console.print(f"[cyan]Saved chat history:[/] showing {len(messages)} of {total} messages")
        for message in messages:
            name = "You" if message.role == "user" else "Miko"
            self.console.print(Panel(message.content, title=f"{name} #{message.id}", border_style="dim"))

    def _logs(self, args: list[str]) -> None:
        query = " ".join(args) if args else None
        logs = self.agent.activity_logs(limit=50, query=query)
        if not logs:
            self.console.print("[cyan]Miko:[/] No activity logs found.")
            return
        table = Table(title="Activity Logs", show_header=True, header_style="bold cyan")
        table.add_column("Time")
        table.add_column("Type")
        table.add_column("Summary")
        for log in logs:
            table.add_row(log.created_at, log.event_type, log.summary)
        self.console.print(table)

    def _journal(self, args: list[str]) -> None:
        limit = self._optional_limit(args, default=10, maximum=50)
        if limit is None:
            self.console.print("[yellow]Use:[/] journal or journal <number>")
            return
        entries = self.agent.journal_entries(limit=limit)
        if not entries:
            self.console.print("[cyan]Miko:[/] I haven't written any journal reflections yet.")
            return
        for entry in entries:
            self.console.print(
                Panel(
                    entry.content,
                    title=f"{entry.title}  [{entry.created_at}]",
                    border_style="magenta",
                )
            )

    def _safe(self, args: list[str]) -> None:
        limit = self._optional_limit(args, default=10, maximum=50)
        if limit is None:
            self.console.print("[yellow]Use:[/] safe or safe <number>")
            return
        memories = self.agent.safe_memories(limit=limit)
        if not memories:
            self.console.print("[cyan]Miko:[/] The Memory Safe is empty right now.")
            return
        for memory in memories:
            body = f"{memory.summary}\n\nReason preserved: {memory.reason}"
            self.console.print(
                Panel(
                    body,
                    title=f"{memory.title}  [importance {memory.importance}/5]",
                    border_style="green",
                )
            )

    def _chat(self, text: str) -> None:
        try:
            self._print_stream(self.agent.chat_stream(self.session, text))
        except OllamaUnavailable as exc:
            self.console.print(f"[red]Miko:[/] {exc}")
            self.console.print("Start Ollama and make sure the configured model is pulled.")

    def _print_stream(self, chunks: Iterable[str]) -> None:
        self.console.print("[bold cyan]Miko:[/] ", end="")
        collected: list[str] = []
        try:
            for chunk in chunks:
                collected.append(chunk)
                self.console.print(chunk, end="")
            self.console.print()
        except OllamaUnavailable as exc:
            self.console.print(f"\n[red]Miko:[/] {exc}")
            self.console.print("Start Ollama and make sure the configured model is pulled.")
            return

        text = "".join(collected).strip()
        if "```" in text or "\n#" in text:
            self.console.print(Markdown(text))

    @staticmethod
    def _clean_arg(value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]
        return value

    @staticmethod
    def _optional_limit(args: list[str], default: int, maximum: int) -> int | None:
        if not args:
            return default
        try:
            return max(1, min(maximum, int(args[0])))
        except ValueError:
            return None
