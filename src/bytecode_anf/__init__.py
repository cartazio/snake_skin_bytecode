"""
bytecode-anf: Recover ANF-style AST from Python bytecode with annotation flow.

Based on:
- Danvy's defunctionalization (stack machines ↔ CPS ↔ ANF)
- Cousot & Cousot's abstract interpretation framework

The key insight: stack positions ARE implicit let-bindings. 
Each PUSH creates a binding, each POP consumes one.
"""

from .anf import (
    PyObjRef,
    ANFVar,
    ANFAtom,
    ANFPrim,
    ANFCall,
    ANFLet,
    ANFBinding,
    ANFBody,
    KWArg,
    ANFJoin,
    JoinField,
    JoinParam,
    ANFBranch,
    ANFJump,
    ANFReturn,
)

from .stack_to_anf import StackToANF, BasicBlock, CFGBuilder, bytecode_to_anf, print_anf

from .lattice import AnnotationLattice, AnnotatedValue, AbstractStack

from .transfer import (
    TransferRegistry,
    annotates,
    annotates_family,
    get_transfer,
    clear_transfers,
    get_default_registry,
)

from .interpreter import AbstractInterpreter

from .builtin_lattices import TypeLattice, SimpleType

from .opcode_versions import (
    OpcodeInfo,
    OPCODE_VERSIONS,
    get_opcode_info,
    opcodes_for_version,
    opcodes_introduced_in,
)

__all__ = [
    # Value model
    "PyObjRef",
    # ANF AST nodes
    "ANFVar",
    "ANFAtom",
    "ANFPrim",
    "ANFCall",
    "ANFLet",
    "ANFBinding",
    "ANFBody",
    "KWArg",
    "ANFJoin",
    "JoinField",
    "JoinParam",
    "ANFBranch",
    "ANFJump",
    "ANFReturn",
    # Stack -> ANF conversion
    "StackToANF",
    "BasicBlock",
    "CFGBuilder",
    "bytecode_to_anf",
    "print_anf",
    # Abstract interpretation
    "AnnotationLattice",
    "AnnotatedValue",
    "AbstractStack",
    "AbstractInterpreter",
    # Transfer function DSL
    "TransferRegistry",
    "annotates",
    "annotates_family",
    "get_transfer",
    "clear_transfers",
    "get_default_registry",
    # Built-in lattices
    "TypeLattice",
    "SimpleType",
    # Opcode version provenance
    "OpcodeInfo",
    "OPCODE_VERSIONS",
    "get_opcode_info",
    "opcodes_for_version",
    "opcodes_introduced_in",
]

__version__ = "0.4.0"
