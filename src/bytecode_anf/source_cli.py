# pyright: strict
"""Command-line CFG/ANF recovery for Python source files."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

from .errors import FrontendError
from .source_ingestion import SourceCodeUnit, load_source_code_units
from .stack_to_anf import StackToANF


@dataclass(frozen=True, slots=True)
class _Options:
    source: Path
    selected_names: tuple[str, ...]


def _parse_args(argv: Sequence[str] | None) -> _Options:
    parser = argparse.ArgumentParser(
        description=(
            "Compile Python source without importing it and recover CFG-shaped ANF."
        )
    )
    parser.add_argument("source", type=Path, help="Python source file to compile")
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="QUALIFIED_NAME",
        help="recover only this code object; repeat to select multiple objects",
    )
    namespace = parser.parse_args(argv)
    return _Options(
        source=cast(Path, namespace.source),
        selected_names=tuple(cast(list[str], namespace.select)),
    )


def stream_safe_text(text: str, stream: TextIO) -> str:
    """Preserve Unicode when possible and escape only unencodable characters."""
    encoding = cast(str | None, getattr(stream, "encoding", None))
    if encoding is None:
        return text
    return text.encode(encoding, errors="backslashreplace").decode(encoding)


def _render_unit(unit: SourceCodeUnit, stream: TextIO) -> None:
    blocks = StackToANF(unit.code).process_cfg()
    print(f"== {unit.qualified_name} (line {unit.first_line}) ==", file=stream)
    print("exact recovery: complete", file=stream)
    for label in sorted(blocks):
        print(stream_safe_text(str(blocks[label]), stream), file=stream)


def analyze_source(
    source: Path,
    selected_names: Sequence[str] = (),
    *,
    stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    """Recover selected code objects and return a command-style status code."""
    units = load_source_code_units(source)
    requested = set(selected_names)
    selected = [
        unit for unit in units if not requested or unit.qualified_name in requested
    ]
    found = {unit.qualified_name for unit in selected}
    missing = sorted(requested - found)
    if missing:
        print("missing code objects: " + ", ".join(missing), file=error_stream)
        return 2

    status = 0
    for unit in selected:
        try:
            _render_unit(unit, stream)
        except FrontendError as error:
            print(
                f"recovery failed for {unit.qualified_name}: "
                f"{type(error).__name__}: {error}",
                file=error_stream,
            )
            status = 1
            continue
    return status


def main(argv: Sequence[str] | None = None) -> int:
    """Run source recovery from command-line arguments."""
    options = _parse_args(argv)
    try:
        return analyze_source(options.source, options.selected_names)
    except (OSError, SyntaxError, UnicodeError) as error:
        print(
            f"source ingestion failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
