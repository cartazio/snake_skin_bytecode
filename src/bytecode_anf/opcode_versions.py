"""
Opcode version provenance.

Maps each CPython opcode to the Python version that introduced it
and (optionally) the version that removed it. This is a reference
for humans and tooling — the actual opcode handling is in
stack_to_anf.py and builtin_transfers.py.

Sources:
- CPython source: Python/bytecodes.c (v3.14.3 tag)
- docs.python.org/3/library/dis.html
- docs.python.org/3/whatsnew/{3.10..3.14}.html

Convention:
  introduced: first version where the opcode exists
  removed:    first version where it no longer exists (None = still present)
  notes:      human-readable context
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict


@dataclass(frozen=True)
class OpcodeInfo:
    """Version provenance and semantics summary for one opcode."""
    introduced: str              # e.g. "3.0", "3.11", "3.14"
    removed: Optional[str] = None  # e.g. "3.12" means gone in 3.12+
    stack_effect: Optional[str] = None  # e.g. "+1", "-2", "0"
    notes: str = ""


# ============================================================
# Opcode version map
# ============================================================
# Grouped by era. Only opcodes relevant to bytecode-anf are
# listed; INSTRUMENTED_* and micro-op variants are omitted.

OPCODE_VERSIONS: Dict[str, OpcodeInfo] = {
    # === Ancient (pre-3.6, still present) ===
    "NOP":              OpcodeInfo("2.4", notes="No operation"),
    "POP_TOP":          OpcodeInfo("1.0", stack_effect="-1"),
    "ROT_TWO":          OpcodeInfo("1.0", removed="3.12", stack_effect="0",
                                   notes="Replaced by SWAP in 3.12"),
    "ROT_THREE":        OpcodeInfo("1.0", removed="3.12", stack_effect="0",
                                   notes="Replaced by SWAP in 3.12"),
    "DUP_TOP":          OpcodeInfo("1.0", removed="3.12", stack_effect="+1",
                                   notes="Replaced by COPY in 3.12"),
    "UNARY_NEGATIVE":   OpcodeInfo("1.0", stack_effect="0"),
    "UNARY_POSITIVE":   OpcodeInfo("1.0", stack_effect="0"),
    "UNARY_NOT":        OpcodeInfo("1.0", stack_effect="0"),
    "UNARY_INVERT":     OpcodeInfo("1.0", stack_effect="0"),
    "GET_ITER":         OpcodeInfo("2.1", stack_effect="0"),
    "RETURN_VALUE":     OpcodeInfo("1.0", stack_effect="-1"),
    "YIELD_VALUE":      OpcodeInfo("2.2", stack_effect="-1"),
    "IMPORT_NAME":      OpcodeInfo("1.0", stack_effect="-1"),
    "IMPORT_FROM":      OpcodeInfo("1.0", stack_effect="+1"),
    "POP_EXCEPT":       OpcodeInfo("3.0", stack_effect="-1"),
    "STORE_NAME":       OpcodeInfo("1.0", stack_effect="-1"),
    "DELETE_NAME":      OpcodeInfo("1.0", stack_effect="0"),
    "STORE_ATTR":       OpcodeInfo("1.0", stack_effect="-2"),
    "DELETE_ATTR":      OpcodeInfo("1.0", stack_effect="-1"),
    "STORE_GLOBAL":     OpcodeInfo("1.0", stack_effect="-1"),
    "DELETE_GLOBAL":    OpcodeInfo("1.0", stack_effect="0"),
    "LOAD_CONST":       OpcodeInfo("1.0", stack_effect="+1"),
    "LOAD_NAME":        OpcodeInfo("1.0", stack_effect="+1"),
    "LOAD_FAST":        OpcodeInfo("1.0", stack_effect="+1"),
    "STORE_FAST":       OpcodeInfo("1.0", stack_effect="-1"),
    "DELETE_FAST":      OpcodeInfo("1.0", stack_effect="0"),
    "LOAD_GLOBAL":      OpcodeInfo("1.0", stack_effect="+1"),
    "LOAD_ATTR":        OpcodeInfo("1.0", stack_effect="0",
                                   notes="3.12: low bit encodes method loading"),
    "LOAD_DEREF":       OpcodeInfo("2.1", stack_effect="+1"),
    "STORE_DEREF":      OpcodeInfo("2.1", stack_effect="-1"),
    "DELETE_DEREF":     OpcodeInfo("3.2", stack_effect="0"),
    "LOAD_CLOSURE":     OpcodeInfo("2.1", stack_effect="+1"),
    "BUILD_TUPLE":      OpcodeInfo("1.0", stack_effect="-(n-1)"),
    "BUILD_LIST":       OpcodeInfo("1.0", stack_effect="-(n-1)"),
    "BUILD_SET":        OpcodeInfo("2.7", stack_effect="-(n-1)"),
    "BUILD_MAP":        OpcodeInfo("1.0", stack_effect="-(2n-1)"),
    "BUILD_STRING":     OpcodeInfo("3.6", stack_effect="-(n-1)"),
    "BUILD_SLICE":      OpcodeInfo("1.0", stack_effect="-(n-1)"),
    "COMPARE_OP":       OpcodeInfo("1.0", stack_effect="-1"),
    "IS_OP":            OpcodeInfo("3.9", stack_effect="-1"),
    "CONTAINS_OP":      OpcodeInfo("3.9", stack_effect="-1"),
    "JUMP_FORWARD":     OpcodeInfo("1.0", stack_effect="0"),
    "JUMP_BACKWARD":    OpcodeInfo("3.12", stack_effect="0",
                                   notes="Replaces JUMP_ABSOLUTE for back-edges"),
    "JUMP_BACKWARD_NO_INTERRUPT": OpcodeInfo("3.12", stack_effect="0"),
    "JUMP_ABSOLUTE":    OpcodeInfo("1.0", removed="3.12", stack_effect="0"),
    "POP_JUMP_IF_TRUE": OpcodeInfo("3.1", stack_effect="-1"),
    "POP_JUMP_IF_FALSE": OpcodeInfo("3.1", stack_effect="-1"),
    "FOR_ITER":         OpcodeInfo("1.0", stack_effect="+1"),
    "UNPACK_SEQUENCE":  OpcodeInfo("1.0", stack_effect="+(n-1)"),
    "UNPACK_EX":        OpcodeInfo("3.0", stack_effect="+n"),
    "STORE_SUBSCR":     OpcodeInfo("1.0", stack_effect="-3"),
    "DELETE_SUBSCR":    OpcodeInfo("1.0", stack_effect="-2"),
    "RAISE_VARARGS":    OpcodeInfo("1.0", stack_effect="-n"),
    "RERAISE":          OpcodeInfo("3.9", stack_effect="0"),
    "MAKE_FUNCTION":    OpcodeInfo("1.0", stack_effect="0"),
    "LOAD_BUILD_CLASS": OpcodeInfo("3.0", stack_effect="+1"),
    "SETUP_ANNOTATIONS": OpcodeInfo("3.6", stack_effect="0"),
    "LIST_APPEND":      OpcodeInfo("2.7", stack_effect="-1"),
    "SET_ADD":          OpcodeInfo("2.7", stack_effect="-1"),
    "MAP_ADD":          OpcodeInfo("3.1", stack_effect="-2"),
    "PUSH_EXC_INFO":    OpcodeInfo("3.11", stack_effect="+1"),
    "CHECK_EXC_MATCH":  OpcodeInfo("3.11", stack_effect="0"),

    # === Pre-3.11 call machinery (removed 3.12) ===
    "CALL_FUNCTION":    OpcodeInfo("1.0", removed="3.12", stack_effect="-n",
                                   notes="Replaced by PUSH_NULL + CALL"),
    "CALL_FUNCTION_KW": OpcodeInfo("3.6", removed="3.12", stack_effect="-n"),
    "CALL_METHOD":      OpcodeInfo("3.7", removed="3.12", stack_effect="-n"),
    "LOAD_METHOD":      OpcodeInfo("3.7", removed="3.12", stack_effect="+1",
                                   notes="Folded into LOAD_ATTR with low-bit flag"),

    # === Python 3.10 ===
    "MATCH_MAPPING":    OpcodeInfo("3.10", stack_effect="0"),
    "MATCH_SEQUENCE":   OpcodeInfo("3.10", stack_effect="0"),
    "MATCH_KEYS":       OpcodeInfo("3.10", stack_effect="+1"),
    "MATCH_CLASS":      OpcodeInfo("3.10", stack_effect="-n"),
    "POP_JUMP_IF_NONE": OpcodeInfo("3.10", stack_effect="-1"),
    "POP_JUMP_IF_NOT_NONE": OpcodeInfo("3.10", stack_effect="-1"),

    # === Python 3.11 ===
    "RESUME":           OpcodeInfo("3.11", stack_effect="0",
                                   notes="Entry point marker, no semantic effect"),
    "PUSH_NULL":        OpcodeInfo("3.11", stack_effect="+1",
                                   notes="Part of 3.11+ call protocol"),
    "PRECALL":          OpcodeInfo("3.11", removed="3.12", stack_effect="0"),
    "CALL":             OpcodeInfo("3.11", stack_effect="-n",
                                   notes="3.11+ unified call opcode"),
    "CACHE":            OpcodeInfo("3.11", stack_effect="0",
                                   notes="Interpreter cache slot, invisible to dis"),
    "BINARY_OP":        OpcodeInfo("3.11", stack_effect="-1",
                                   notes="Replaces all BINARY_* / INPLACE_* ops"),
    "COPY":             OpcodeInfo("3.11", stack_effect="+1",
                                   notes="Replaces DUP_TOP"),
    "SWAP":             OpcodeInfo("3.11", stack_effect="0",
                                   notes="Replaces ROT_TWO/ROT_THREE"),
    "RETURN_GENERATOR": OpcodeInfo("3.11", stack_effect="0"),
    "SEND":             OpcodeInfo("3.11", stack_effect="0"),
    "COPY_FREE_VARS":   OpcodeInfo("3.11", stack_effect="0"),
    "MAKE_CELL":        OpcodeInfo("3.11", stack_effect="0"),

    # === Python 3.12 ===
    "LOAD_FAST_AND_CLEAR": OpcodeInfo("3.12", stack_effect="+1",
                                       notes="Comprehension scoping"),
    "LOAD_FAST_CHECK":  OpcodeInfo("3.12", stack_effect="+1",
                                   notes="LOAD_FAST with UnboundLocalError check"),
    "BINARY_SLICE":     OpcodeInfo("3.12", stack_effect="-2",
                                   notes="Dedicated container[start:end]"),
    "STORE_SLICE":      OpcodeInfo("3.12", stack_effect="-4",
                                   notes="Dedicated container[start:end] = value"),
    "CALL_INTRINSIC_1": OpcodeInfo("3.12", stack_effect="0"),
    "CALL_INTRINSIC_2": OpcodeInfo("3.12", stack_effect="-1"),
    "LOAD_SUPER_ATTR":  OpcodeInfo("3.12", stack_effect="-2",
                                   notes="Optimized super() attribute access"),
    "LOAD_FROM_DICT_OR_DEREF": OpcodeInfo("3.12", stack_effect="0",
                                           notes="Annotation scope in class bodies"),
    "LOAD_FROM_DICT_OR_GLOBALS": OpcodeInfo("3.12", stack_effect="0"),
    "END_FOR":          OpcodeInfo("3.12", stack_effect="-1",
                                   notes="Renamed to POP_ITER in 3.14"),
    "END_SEND":         OpcodeInfo("3.12", stack_effect="-1"),
    "RETURN_CONST":     OpcodeInfo("3.12", stack_effect="0",
                                   notes="Fused LOAD_CONST + RETURN_VALUE"),
    "EXIT_INIT_CHECK":  OpcodeInfo("3.12", stack_effect="-1"),
    "CALL_FUNCTION_EX": OpcodeInfo("3.5", stack_effect="-n",
                                   notes="*args/**kwargs calls, still present in 3.14"),
    "BUILD_CONST_KEY_MAP": OpcodeInfo("3.6", stack_effect="-(n)"),
    "LIST_EXTEND":      OpcodeInfo("3.9", stack_effect="-1"),
    "SET_UPDATE":       OpcodeInfo("3.9", stack_effect="-1"),
    "DICT_UPDATE":      OpcodeInfo("3.9", stack_effect="-1"),
    "DICT_MERGE":       OpcodeInfo("3.9", stack_effect="-1"),
    "BEFORE_WITH":      OpcodeInfo("3.11", stack_effect="+1"),
    "CLEANUP_THROW":    OpcodeInfo("3.12", stack_effect="-1"),

    # === Python 3.13 ===
    "LOAD_FAST_LOAD_FAST": OpcodeInfo("3.13", stack_effect="+2",
                                       notes="Superinstruction: pushes two locals"),
    "STORE_FAST_STORE_FAST": OpcodeInfo("3.13", stack_effect="-2",
                                         notes="Superinstruction: stores two locals"),
    "STORE_FAST_LOAD_FAST": OpcodeInfo("3.13", stack_effect="0",
                                        notes="Superinstruction: store then load"),
    "TO_BOOL":          OpcodeInfo("3.13", stack_effect="0",
                                   notes="Explicit bool(TOS) conversion"),
    "CALL_KW":          OpcodeInfo("3.13", stack_effect="-n",
                                   notes="Replaces CALL_FUNCTION_KW"),
    "FORMAT_SIMPLE":    OpcodeInfo("3.13", stack_effect="0",
                                   notes="TOS.__format__('') for f-strings"),
    "FORMAT_WITH_SPEC": OpcodeInfo("3.13", stack_effect="-1",
                                   notes="val.__format__(spec) for f-strings"),
    "CONVERT_VALUE":    OpcodeInfo("3.13", stack_effect="0",
                                   notes="F-string conversion: 1=str, 2=repr, 3=ascii"),
    "SET_FUNCTION_ATTRIBUTE": OpcodeInfo("3.13", stack_effect="-1",
                                          notes="Replaces MAKE_FUNCTION flags"),
    "LOAD_LOCALS":      OpcodeInfo("3.13", stack_effect="+1",
                                   notes="Pushes locals() dict"),
    "STORE_FAST_MAYBE_NULL": OpcodeInfo("3.13", stack_effect="-1",
                                         notes="Pseudo-op: STORE_FAST that accepts NULL"),

    # === Python 3.14 ===
    "LOAD_FAST_BORROW": OpcodeInfo("3.14", stack_effect="+1",
                                   notes="LOAD_FAST with borrowed reference (refcount opt)"),
    "LOAD_FAST_BORROW_LOAD_FAST_BORROW": OpcodeInfo("3.14", stack_effect="+2",
                                                      notes="Superinstruction: two borrowed loads"),
    "LOAD_SMALL_INT":   OpcodeInfo("3.14", stack_effect="+1",
                                   notes="Optimized push for ints 0-255"),
    "LOAD_COMMON_CONSTANT": OpcodeInfo("3.14", stack_effect="+1",
                                        notes="Hardcoded constants (e.g. AssertionError)"),
    "LOAD_SPECIAL":     OpcodeInfo("3.14", stack_effect="+1",
                                   notes="Special method lookup on TOS"),
    "NOT_TAKEN":        OpcodeInfo("3.14", stack_effect="0",
                                   notes="Branch hint NOP for sys.monitoring"),
    "POP_ITER":         OpcodeInfo("3.14", stack_effect="-1",
                                   notes="Pop iterator; replaces END_FOR"),
    "BUILD_INTERPOLATION": OpcodeInfo("3.14", stack_effect="-n",
                                       notes="PEP 750: template string Interpolation"),
    "BUILD_TEMPLATE":   OpcodeInfo("3.14", stack_effect="-1",
                                   notes="PEP 750: template string Template"),
}


def get_opcode_info(opname: str) -> Optional[OpcodeInfo]:
    """Look up version provenance for an opcode."""
    return OPCODE_VERSIONS.get(opname)


def opcodes_for_version(version: str) -> list[str]:
    """Return all opcodes available in a given Python version.
    
    Args:
        version: e.g. "3.12", "3.14"
    """
    result = []
    for name, info in OPCODE_VERSIONS.items():
        if info.introduced <= version:
            if info.removed is None or info.removed > version:
                result.append(name)
    return sorted(result)


def opcodes_introduced_in(version: str) -> list[str]:
    """Return opcodes first introduced in exactly this version."""
    return sorted(
        name for name, info in OPCODE_VERSIONS.items()
        if info.introduced == version
    )
