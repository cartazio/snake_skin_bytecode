"""Typed failures for strict bytecode conversion and analysis.

Strict mode is the public default and uses this hierarchy so a compiler front
end never has to parse warning strings or inspect placeholder IR to discover
that translation was incomplete.  Explicit permissive mode remains available
for exploratory inspection only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .opcode_identity import (
    OpcodeIdentity,
    UnknownOpcode,
    identify_opcode,
)


@dataclass(frozen=True)
class InstructionSite:
    """Stable location information copied from a ``dis.Instruction``."""

    opcode: OpcodeIdentity
    offset: int | None

    @classmethod
    def from_instruction(cls, instruction: Any) -> InstructionSite:
        raw_code = getattr(instruction, "opcode", None)
        return cls(
            opcode=identify_opcode(
                str(getattr(instruction, "opname", "<unknown>")),
                raw_code if isinstance(raw_code, int) else None,
            ),
            offset=getattr(instruction, "offset", None),
        )

    @property
    def opname(self) -> str:
        if isinstance(self.opcode, UnknownOpcode):
            return self.opcode.opname
        return self.opcode.value

    def render(self) -> str:
        if self.offset is None:
            return self.opname
        return f"{self.opname} at bytecode offset {self.offset}"


class FrontendError(Exception):
    """Base class for failures that make a strict result unsound."""

    def __init__(
        self,
        detail: str,
        *,
        instruction: Any = None,
        site: InstructionSite | None = None,
    ) -> None:
        if instruction is not None and site is not None:
            raise TypeError("provide instruction or site, not both")
        self.detail = detail
        self.site = (
            InstructionSite.from_instruction(instruction)
            if instruction is not None
            else site
        )
        location = f" [{self.site.render()}]" if self.site is not None else ""
        super().__init__(f"{detail}{location}")

    @property
    def opname(self) -> str | None:
        return self.site.opname if self.site is not None else None

    @property
    def offset(self) -> int | None:
        return self.site.offset if self.site is not None else None

    @property
    def opcode_identity(self) -> OpcodeIdentity | None:
        return self.site.opcode if self.site is not None else None


class UnsupportedOpcodeError(FrontendError):
    """The front end has no exact semantics for an encountered opcode."""


class UnsupportedCallError(UnsupportedOpcodeError):
    """A call form cannot be represented exactly by the current IR."""


class StackDisciplineError(FrontendError):
    """Bytecode stack use is inconsistent with the simulated stack."""


class StackUnderflowError(StackDisciplineError):
    """An instruction requires more operands than are available."""


class StackOverflowError(StackDisciplineError):
    """Simulation exceeded the code object's declared maximum stack depth."""


class StackMergeError(StackDisciplineError):
    """Control-flow predecessors reach a merge with incompatible stacks."""


class TransferFailureError(FrontendError):
    """A registered abstract transfer function failed or broke its contract."""


class IRInvariantError(FrontendError):
    """Emitted ANF violates the shape required by the typed IR."""


class FixpointLimitError(FrontendError):
    """Abstract interpretation stopped before its worklist reached a fixpoint."""


def unsupported_instruction_error(
    instruction: Any,
    detail: str | None = None,
) -> UnsupportedOpcodeError:
    """Classify unsupported call machinery separately from other opcodes."""

    opname = str(getattr(instruction, "opname", "<unknown>"))
    error_type = (
        UnsupportedCallError
        if opname.startswith("CALL") or opname in {"KW_NAMES", "PRECALL"}
        else UnsupportedOpcodeError
    )
    return error_type(
        detail or f"no exact frontend semantics for {opname}",
        instruction=instruction,
    )
