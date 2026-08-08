# pyright: strict
"""Compile Python source into discoverable code objects without importing it."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from tokenize import open as open_python_source
from types import CodeType


@dataclass(frozen=True, slots=True)
class SourceCodeUnit:
    """One named code object recovered from a source file."""

    path: Path
    qualified_name: str
    code: CodeType

    @property
    def first_line(self) -> int:
        return self.code.co_firstlineno


def compile_source_file(path: str | Path) -> CodeType:
    """Compile *path* without executing its module body."""
    source_path = Path(path)
    with open_python_source(str(source_path)) as stream:
        source = stream.read()
    return compile(source, str(source_path), "exec", dont_inherit=True)


def iter_code_objects(
    root: CodeType,
    *,
    parent_name: str = "",
) -> Iterator[tuple[str, CodeType]]:
    """Yield nested code objects in source order with stable qualified names."""
    for constant in root.co_consts:
        if not isinstance(constant, CodeType):
            continue
        qualified_name = (
            f"{parent_name}.{constant.co_name}" if parent_name else constant.co_name
        )
        yield qualified_name, constant
        yield from iter_code_objects(constant, parent_name=qualified_name)


def load_source_code_units(path: str | Path) -> tuple[SourceCodeUnit, ...]:
    """Compile a source file and enumerate every nested code object."""
    source_path = Path(path)
    root = compile_source_file(source_path)
    return tuple(
        SourceCodeUnit(source_path, qualified_name, code)
        for qualified_name, code in iter_code_objects(root)
    )
