"""
ANF (A-Normal Form) AST nodes.

ANF requires all intermediate results to be let-bound.
No nested compound expressions — only atomic subexpressions.

The stack machine naturally produces ANF: each operation
consumes named operands from the stack and pushes a named result.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional, Union


@dataclass(frozen=True)
class ANFVar:
    """A variable name in ANF."""
    name: str
    
    def __repr__(self) -> str:
        return self.name


@dataclass(frozen=True)
class ANFAtom:
    """
    Atomic expression: variable reference or constant.
    
    In ANF, all operands must be atomic (no nested compound expressions).
    """
    value: Union[ANFVar, int, float, str, bool, None, tuple, frozenset]
    
    def __repr__(self) -> str:
        if isinstance(self.value, ANFVar):
            return repr(self.value)
        return repr(self.value)
    
    @property
    def is_var(self) -> bool:
        return isinstance(self.value, ANFVar)
    
    @property
    def is_const(self) -> bool:
        return not self.is_var


@dataclass
class ANFPrim:
    """
    Primitive operation application.
    
    All arguments must be atomic (ANFAtom).
    """
    op: str
    args: List[ANFAtom]
    
    def __repr__(self) -> str:
        args_str = " ".join(map(repr, self.args))
        return f"({self.op} {args_str})"


@dataclass
class ANFCall:
    """
    Function call.
    
    Both func and all args must be atomic.
    """
    func: ANFAtom
    args: List[ANFAtom]
    kwargs: Optional[dict] = None
    
    def __repr__(self) -> str:
        args_str = " ".join(map(repr, self.args))
        if self.kwargs:
            kw_str = " ".join(f"{k}={v}" for k, v in self.kwargs.items())
            return f"(call {self.func} {args_str} {kw_str})"
        return f"(call {self.func} {args_str})"


@dataclass
class ANFLet:
    """
    Let-binding: let var = rhs in body.
    
    This is the core ANF construct — all intermediate results
    are explicitly named via let-binding.
    """
    var: ANFVar
    rhs: Union[ANFAtom, ANFPrim, ANFCall, 'ANFPhi']
    body: Optional[ANFLet] = None  # None for tail position
    
    def __repr__(self) -> str:
        if self.body is None:
            return f"(let [{self.var} {self.rhs}])"
        return f"(let [{self.var} {self.rhs}] {self.body})"


# === Phi nodes (CFG merge points) ===

@dataclass
class ANFPhi:
    """
    Phi node at a CFG join point.
    
    When control flow merges (after if/else, loop entry),
    incoming values from different predecessors are unified.
    Each (label, atom) pair maps a predecessor block to its value.
    """
    args: List[tuple]  # List of (block_label: int, value: ANFAtom)
    
    def __repr__(self) -> str:
        pairs = ", ".join(f"B{label}:{val}" for label, val in self.args)
        return f"(phi {pairs})"


# === Control flow terminators ===

@dataclass
class ANFBranch:
    """Conditional branch terminator."""
    cond: ANFAtom
    true_label: int
    false_label: int
    
    def __repr__(self) -> str:
        return f"(if {self.cond} goto {self.true_label} else {self.false_label})"


@dataclass
class ANFJump:
    """Unconditional jump terminator."""
    label: int
    
    def __repr__(self) -> str:
        return f"(goto {self.label})"


@dataclass
class ANFReturn:
    """Return terminator."""
    value: ANFAtom
    
    def __repr__(self) -> str:
        return f"(return {self.value})"


# Type alias for any ANF expression
ANFExpr = Union[ANFAtom, ANFPrim, ANFCall, ANFLet, ANFPhi]
ANFTerminator = Union[ANFBranch, ANFJump, ANFReturn]
