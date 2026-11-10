from __future__ import annotations

import pytest

from miko_app.files import FileReadError, FileReader


def test_reads_unknown_text_file(tmp_path):
    note = tmp_path / "notes.custom"
    note.write_text("Miko can read plain text even with an unknown extension.", encoding="utf-8")

    result = FileReader(max_chars=1000).read(str(note))

    assert result.kind == "custom"
    assert "plain text" in result.content


def test_refuses_binary_file(tmp_path):
    binary = tmp_path / "program.exe"
    binary.write_bytes(b"MZ\x00\x00binary")

    with pytest.raises(FileReadError):
        FileReader(max_chars=1000).read(str(binary))


def test_formats_json(tmp_path):
    data = tmp_path / "data.json"
    data.write_text('{"name":"Miko","version":1}', encoding="utf-8")

    result = FileReader(max_chars=1000).read(str(data))

    assert '"name": "Miko"' in result.content
