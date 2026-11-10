from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import fitz
from docx import Document
from openpyxl import load_workbook


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".csv",
    ".tsv",
    ".xml",
    ".svg",
    ".sql",
    ".log",
    ".bat",
    ".ps1",
    ".sh",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".cs",
    ".go",
    ".rs",
    ".php",
    ".rb",
}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx"}
KNOWN_BINARY_EXTENSIONS = {
    ".exe",
    ".dll",
    ".bin",
    ".dat",
    ".iso",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp3",
    ".wav",
    ".mp4",
    ".mov",
    ".avi",
}


@dataclass(frozen=True)
class ReadFileResult:
    path: Path
    name: str
    kind: str
    content: str


class FileReadError(RuntimeError):
    pass


class FileReader:
    def __init__(self, max_chars: int):
        self.max_chars = max_chars

    def read(self, raw_path: str) -> ReadFileResult:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise FileReadError(f"I couldn't find that file: {path}")
        if not path.is_file():
            raise FileReadError(f"That path is not a file: {path}")

        suffix = path.suffix.lower()
        if suffix in KNOWN_BINARY_EXTENSIONS:
            raise FileReadError(
                "That looks like a binary, media, or archive file. I can read text and documents, "
                "but I can't understand raw binary content in v0.1."
            )

        if suffix == ".pdf":
            content = self._read_pdf(path)
        elif suffix == ".docx":
            content = self._read_docx(path)
        elif suffix == ".xlsx":
            content = self._read_xlsx(path)
        elif suffix in {".csv", ".tsv"}:
            content = self._read_delimited(path, delimiter="\t" if suffix == ".tsv" else ",")
        elif suffix == ".json":
            content = self._read_json(path)
        else:
            content = self._read_text(path)

        content = content.strip()
        if not content:
            raise FileReadError("I opened the file, but I couldn't find readable text inside it.")

        if len(content) > self.max_chars:
            content = content[: self.max_chars] + "\n\n[Content truncated for Miko v0.1.]"

        kind = suffix.lstrip(".") if suffix else "text"
        return ReadFileResult(path=path, name=path.name, kind=kind, content=content)

    @staticmethod
    def _read_text(path: Path) -> str:
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            raise FileReadError(
                "That file contains binary data, not readable text. I can only load readable content in v0.1."
            )
        for encoding in ("utf-8", "utf-8-sig", "cp1252"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise FileReadError("I couldn't decode that text file. Try saving it as UTF-8.")

    @staticmethod
    def _read_pdf(path: Path) -> str:
        try:
            pieces: list[str] = []
            with fitz.open(path) as doc:
                for page_number, page in enumerate(doc, start=1):
                    text = page.get_text("text").strip()
                    if text:
                        pieces.append(f"[Page {page_number}]\n{text}")
            return "\n\n".join(pieces)
        except Exception as exc:
            raise FileReadError(f"I couldn't read that PDF: {exc}") from exc

    @staticmethod
    def _read_docx(path: Path) -> str:
        try:
            document = Document(path)
            paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
            table_rows: list[str] = []
            for table_index, table in enumerate(document.tables, start=1):
                table_rows.append(f"[Table {table_index}]")
                for row in table.rows:
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(cells):
                        table_rows.append(" | ".join(cells))
            return "\n".join(paragraphs + table_rows)
        except Exception as exc:
            raise FileReadError(f"I couldn't read that Word document: {exc}") from exc

    @staticmethod
    def _read_xlsx(path: Path) -> str:
        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
            pieces: list[str] = []
            for sheet in workbook.worksheets:
                pieces.append(f"[Sheet: {sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    values = ["" if value is None else str(value) for value in row]
                    if any(value.strip() for value in values):
                        pieces.append(" | ".join(values))
            workbook.close()
            return "\n".join(pieces)
        except Exception as exc:
            raise FileReadError(f"I couldn't read that spreadsheet: {exc}") from exc

    @staticmethod
    def _read_delimited(path: Path, delimiter: str) -> str:
        text = FileReader._read_text(path)
        rows = csv.reader(text.splitlines(), delimiter=delimiter)
        return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)

    @staticmethod
    def _read_json(path: Path) -> str:
        text = FileReader._read_text(path)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        return json.dumps(parsed, indent=2, ensure_ascii=False)
