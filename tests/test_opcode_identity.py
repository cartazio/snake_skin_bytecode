# pyright: strict
"""Closed opcode identity distinguishes known cases from one unknown case."""

import dis
from types import SimpleNamespace

from bytecode_anf import (
    OPCODE_VERSIONS,
    KnownOpcode,
    UnknownOpcode,
    identify_opcode,
)
from bytecode_anf.errors import unsupported_instruction_error


def test_every_current_runtime_opcode_has_a_known_case() -> None:
    unknown = {
        opname: identity
        for opname, raw_code in dis.opmap.items()
        if isinstance(
            identity := identify_opcode(opname, raw_code),
            UnknownOpcode,
        )
    }

    assert unknown == {}


def test_every_version_catalog_opcode_has_a_known_case() -> None:
    assert {opcode.value for opcode in KnownOpcode}.issuperset(OPCODE_VERSIONS)


def test_future_opcode_uses_the_single_unknown_case() -> None:
    identity = identify_opcode("FUTURE_OPCODE", 255)

    assert identity == UnknownOpcode(opname="FUTURE_OPCODE", raw_code=255)


def test_known_identity_does_not_claim_supported_semantics() -> None:
    instruction = SimpleNamespace(
        opname="FORMAT_VALUE",
        opcode=dis.opmap["FORMAT_VALUE"],
        arg=0,
        argval=0,
        offset=6,
    )

    error = unsupported_instruction_error(instruction)

    assert error.opcode_identity is KnownOpcode.FORMAT_VALUE
