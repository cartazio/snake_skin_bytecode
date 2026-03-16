"""
Transfer function registration DSL.

Provides a TransferRegistry class and decorators for registering
opcode handlers:
- @registry.annotates('OPCODE'): exact opcode match
- @registry.annotates_family('PREFIX_'): prefix family match

Transfer functions have signature:
    def xfer(stack: AbstractStack[A], instr, **ctx) -> Optional[Result]

Context dict contains:
    - locals_ann: Dict[str, A] -- annotation for each local variable
    - globals_ann: Dict[str, A] -- annotation for globals (if available)
    - code: CodeType -- the code object being analyzed

Backwards compatibility: module-level annotates(), get_transfer(), etc.
operate on a default global registry. New code should prefer explicit
TransferRegistry instances to avoid cross-analysis contamination.
"""

from __future__ import annotations
from typing import Callable, Dict, Optional, List, Any


class TransferRegistry:
    """
    Scoped registry of transfer functions for abstract interpretation.

    Isolates registrations so concurrent analyses with different lattices
    do not clobber each other.
    """

    def __init__(self):
        self._exact: Dict[str, Callable] = {}
        self._family: Dict[str, Callable] = {}

    def annotates(self, *opcodes: str):
        """Decorator: register a transfer function for specific opcodes."""
        def decorator(fn: Callable) -> Callable:
            for op in opcodes:
                self._exact[op] = fn
            return fn
        return decorator

    def annotates_family(self, prefix: str):
        """Decorator: register a transfer function for an opcode family."""
        def decorator(fn: Callable) -> Callable:
            self._family[prefix] = fn
            return fn
        return decorator

    def get_transfer(self, opname: str) -> Optional[Callable]:
        """
        Look up the transfer function for an opcode.

        Priority:
        1. Exact match via annotates()
        2. Longest matching prefix via annotates_family()
        3. None
        """
        if opname in self._exact:
            return self._exact[opname]

        best_match = None
        best_len = 0
        for prefix, fn in self._family.items():
            if opname.startswith(prefix) and len(prefix) > best_len:
                best_match = fn
                best_len = len(prefix)

        return best_match

    def list_transfers(self) -> Dict[str, List[str]]:
        """List all registered transfer functions."""
        return {
            "exact": list(self._exact.keys()),
            "families": list(self._family.keys()),
        }

    def clear(self) -> None:
        """Clear all registrations."""
        self._exact.clear()
        self._family.clear()

    def copy(self) -> TransferRegistry:
        """Shallow copy of the registry."""
        new = TransferRegistry()
        new._exact = dict(self._exact)
        new._family = dict(self._family)
        return new


# ============================================================
# Default global registry (backwards compatibility)
# ============================================================

_default_registry = TransferRegistry()


def annotates(*opcodes: str):
    """Register on the default global registry."""
    return _default_registry.annotates(*opcodes)


def annotates_family(prefix: str):
    """Register on the default global registry."""
    return _default_registry.annotates_family(prefix)


def get_transfer(opname: str) -> Optional[Callable]:
    """Look up in the default global registry."""
    return _default_registry.get_transfer(opname)


def list_transfers() -> Dict[str, List[str]]:
    """List from the default global registry."""
    return _default_registry.list_transfers()


def clear_transfers() -> None:
    """Clear the default global registry."""
    _default_registry.clear()


def get_default_registry() -> TransferRegistry:
    """Return the default global registry."""
    return _default_registry


def register_defaults(lattice) -> None:
    """
    Register default transfer functions for common opcodes
    on the global registry.
    """
    from .builtin_transfers import register_builtin_transfers
    register_builtin_transfers(lattice)
