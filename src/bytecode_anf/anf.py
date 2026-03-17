"""
ANF (A-Normal Form) AST nodes.

ANF requires all intermediate results to be let-bound.
No nested compound expressions; only atomic subexpressions.

The stack machine naturally produces ANF: each operation
consumes named operands from the stack and pushes a named result.

Join points follow codata/additive-& semantics (shared closure,
per-path observations) rather than SSA-style phi nodes.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional, Union


# === Atoms and variables ===

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


# === Compound expressions ===

@dataclass(frozen=True)
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


@dataclass(frozen=True)
class KWArg:
    """A single keyword argument: name=value."""
    name: str
    value: ANFAtom

    def __repr__(self) -> str:
        return f"{self.name}={self.value}"


@dataclass(frozen=True)
class ANFCall:
    """
    Function call.

    Both func and all args must be atomic.
    """
    func: ANFAtom
    args: List[ANFAtom]
    kwargs: Optional[List[KWArg]] = None

    def __repr__(self) -> str:
        args_str = " ".join(map(repr, self.args))
        if self.kwargs:
            kw_str = " ".join(repr(kw) for kw in self.kwargs)
            return f"(call {self.func} {args_str} {kw_str})"
        return f"(call {self.func} {args_str})"


# === Bindings ===

@dataclass(frozen=True)
class ANFBinding:
    """A single let-binding: var = rhs.

    The fundamental unit of ANF: every intermediate result is named.
    """
    var: ANFVar
    rhs: Union[ANFAtom, ANFPrim, ANFCall]

    def __repr__(self) -> str:
        return f"(let {self.var} = {self.rhs})"


@dataclass
class ANFLet:
    """
    Let-binding: let var = rhs in body.

    This is the nested/recursive ANF construct.
    For flat binding sequences, use ANFBody.
    """
    var: ANFVar
    rhs: Union[ANFAtom, ANFPrim, ANFCall]
    body: Optional[ANFLet] = None  # None for tail position

    def __repr__(self) -> str:
        if self.body is None:
            return f"(let [{self.var} {self.rhs}])"
        return f"(let [{self.var} {self.rhs}] {self.body})"


# === Bodies (named binding sequences) ===

@dataclass
class ANFBody:
    """A sequence of let-bindings with a terminator.

    Named type for what was previously List[Tuple[ANFVar, ANFExpr]].
    Used by BasicBlock, JoinField, and anywhere a binding sequence appears.
    """
    bindings: List[ANFBinding] = field(default_factory=list)
    terminator: Optional[ANFTerminator] = None

    def add(self, var: ANFVar, rhs: Union[ANFAtom, ANFPrim, ANFCall]) -> None:
        self.bindings.append(ANFBinding(var, rhs))

    def __repr__(self) -> str:
        lines = [repr(b) for b in self.bindings]
        if self.terminator:
            lines.append(repr(self.terminator))
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self.bindings)

    def __iter__(self):
        return iter(self.bindings)


# === Control flow terminators ===

@dataclass(frozen=True)
class ANFBranch:
    """Conditional branch terminator."""
    cond: ANFAtom
    true_label: int
    false_label: int

    def __repr__(self) -> str:
        return f"(if {self.cond} goto {self.true_label} else {self.false_label})"


@dataclass(frozen=True)
class ANFJump:
    """Unconditional jump terminator."""
    label: int

    def __repr__(self) -> str:
        return f"(goto {self.label})"


@dataclass(frozen=True)
class ANFReturn:
    """Return terminator."""
    value: ANFAtom

    def __repr__(self) -> str:
        return f"(return {self.value})"


ANFTerminator = Union[ANFBranch, ANFJump, ANFReturn]


# === Join points (codata / additive &) ===

@dataclass(frozen=True)
class JoinParam:
    """A parameter of a join field: path-specific binding with type."""
    var: ANFVar
    ann: Any = None  # annotation from abstract interpretation

    def __repr__(self) -> str:
        if self.ann is not None:
            return f"{self.var}:{self.ann}"
        return repr(self.var)


@dataclass
class JoinField:
    """One observation/method of a join corecord.

    Each field is a predecessor path with:
    - label: which block this path comes from
    - params: path-specific bindings (what this branch produced)
    - body: this field's continuation (the case RHS)

    All fields of a join share the enclosing closure (additive & semantics).
    """
    label: int
    params: List[JoinParam] = field(default_factory=list)
    body: ANFBody = field(default_factory=ANFBody)

    def __repr__(self) -> str:
        params_str = ", ".join(repr(p) for p in self.params)
        return f".from_B{self.label}({params_str}) → {self.body}"


@dataclass
class ANFJoin:
    """Codata join point: additive & over a shared closure.

    At a CFG merge, instead of SSA phi nodes (first-order data selection),
    we use a corecord where:
    - Fields are predecessor paths, each with its own body
    - All fields share the enclosing closure (the & property)
    - Each field has a type signature (from abstract interpretation)

    This follows GHC's join points, Agda coinductives, and the
    n-arity linear & connective from the Π–Σ type former.
    """
    name: ANFVar
    fields: List[JoinField] = field(default_factory=list)

    def __repr__(self) -> str:
        fields_str = "\n  ".join(repr(f) for f in self.fields)
        return f"(join {self.name}\n  {fields_str})"


# === Type aliases ===

ANFExpr = Union[ANFAtom, ANFPrim, ANFCall, ANFLet, ANFJoin]
