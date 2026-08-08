# pyright: strict
"""Tests for source-file ingestion without module execution."""

from pathlib import Path

from bytecode_anf.source_ingestion import load_source_code_units


def test_source_ingestion_recurses_without_importing(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """def outer():
    def inner():
        return 1
    return inner

class Example:
    def method(self):
        return 2

raise AssertionError('module execution is forbidden')
""",
        encoding="utf-8",
    )

    units = load_source_code_units(source)

    assert [unit.qualified_name for unit in units] == [
        "outer",
        "outer.inner",
        "Example",
        "Example.method",
    ]
    assert [unit.first_line for unit in units] == [1, 2, 6, 7]
