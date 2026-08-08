# pyright: strict
"""Tests for deterministic source-file recovery output."""

from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path

from bytecode_anf.source_cli import analyze_source, stream_safe_text


def test_analyze_selected_source_function(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """def add(left, right):
    return left + right
""",
        encoding="utf-8",
    )
    output = StringIO()
    errors = StringIO()

    status = analyze_source(source, ["add"], stream=output, error_stream=errors)

    assert status == 0
    assert errors.getvalue() == ""
    assert "== add (line 1) ==" in output.getvalue()
    assert "exact recovery: complete" in output.getvalue()
    assert "(+ left right)" in output.getvalue()


def test_analyze_reports_missing_selection(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def present():\n    return 1\n", encoding="utf-8")
    output = StringIO()
    errors = StringIO()

    status = analyze_source(source, ["absent"], stream=output, error_stream=errors)

    assert status == 2
    assert output.getvalue() == ""
    assert errors.getvalue() == "missing code objects: absent\n"


def test_analyze_reports_located_unsupported_semantics(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "def render(value):\n    return f'value={value}'\n",
        encoding="utf-8",
    )
    output = StringIO()
    errors = StringIO()

    status = analyze_source(source, ["render"], stream=output, error_stream=errors)

    assert status == 1
    assert output.getvalue() == ""
    assert "UnsupportedOpcodeError" in errors.getvalue()
    assert "FORMAT_VALUE" in errors.getvalue()
    assert "bytecode offset" in errors.getvalue()


def test_stream_safe_escapes_only_unencodable_text() -> None:
    stream = TextIOWrapper(BytesIO(), encoding="ascii", errors="strict")

    assert stream_safe_text("field → body", stream) == r"field \u2192 body"
