"""
Built-in annotation lattices.

Provides ready-to-use lattices for common analyses:
- TypeLattice: simple type inference
- (future: TaintLattice, IntervalLattice, etc.)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, FrozenSet, Union

from .lattice import AnnotationLattice


@dataclass(frozen=True)
class SimpleType:
    """
    A simple type in our lattice.
    
    Uses string names for flexibility.
    """
    name: str
    
    def __repr__(self) -> str:
        return self.name


class TypeLattice(AnnotationLattice[SimpleType]):
    """
    Simple type lattice for type inference.
    
    Lattice structure:
    
            ⊤ (any)
           /|\\
         num str ...
        /   \\
      int  float
        \\   /
          ⊥ (bottom)
    
    This is a simple demonstration. A real type lattice
    would handle generics, unions, protocols, etc.
    """
    
    # Singleton instances for common types
    INT = SimpleType("int")
    FLOAT = SimpleType("float")
    STR = SimpleType("str")
    BOOL = SimpleType("bool")
    BYTES = SimpleType("bytes")
    NONE = SimpleType("None")
    LIST = SimpleType("list")
    DICT = SimpleType("dict")
    TUPLE = SimpleType("tuple")
    SET = SimpleType("set")
    CALLABLE = SimpleType("callable")
    ITERATOR = SimpleType("iterator")
    TYPE = SimpleType("type")    # class/type objects (themselves PyObjects)
    MODULE = SimpleType("module")
    
    # Compound types
    NUM = SimpleType("num")      # int | float
    SEQUENCE = SimpleType("seq") # list | tuple | str
    
    # Lattice bounds
    ANY = SimpleType("⊤")
    BOTTOM = SimpleType("⊥")
    
    def bottom(self) -> SimpleType:
        return self.BOTTOM
    
    def top(self) -> SimpleType:
        return self.ANY
    
    # Subtype parents: maps each type to its immediate supertype(s).
    # This encodes:
    #   bottom < bool < int < num < top
    #   bottom < float < num < top
    #   bottom < str < seq < top
    #   bottom < list < seq < top
    #   bottom < tuple < seq < top
    #   bottom < {bytes, None, dict, set, callable, iterator} < top
    _PARENTS: Dict[SimpleType, FrozenSet[SimpleType]] = {}

    def _get_parents(self) -> Dict[SimpleType, FrozenSet[SimpleType]]:
        if not TypeLattice._PARENTS:
            TypeLattice._PARENTS = {
                self.BOTTOM: frozenset(),
                self.BOOL:   frozenset({self.INT}),
                self.INT:    frozenset({self.NUM}),
                self.FLOAT:  frozenset({self.NUM}),
                self.NUM:    frozenset({self.ANY}),
                self.STR:    frozenset({self.SEQUENCE}),
                self.LIST:   frozenset({self.SEQUENCE}),
                self.TUPLE:  frozenset({self.SEQUENCE}),
                self.SEQUENCE: frozenset({self.ANY}),
                self.BYTES:  frozenset({self.ANY}),
                self.NONE:   frozenset({self.ANY}),
                self.DICT:   frozenset({self.ANY}),
                self.SET:    frozenset({self.ANY}),
                self.CALLABLE: frozenset({self.ANY}),
                self.ITERATOR: frozenset({self.ANY}),
                self.TYPE:   frozenset({self.CALLABLE}),  # types are callable (instantiation)
                self.MODULE: frozenset({self.ANY}),
                self.ANY:    frozenset(),
            }
        return TypeLattice._PARENTS

    def _ancestors(self, t: SimpleType) -> set[SimpleType]:
        """All ancestors of t, including t itself."""
        parents = self._get_parents()
        result: set[SimpleType] = {t}
        frontier = [t]
        while frontier:
            cur = frontier.pop()
            for p in parents.get(cur, frozenset({self.ANY})):
                if p not in result:
                    result.add(p)
                    frontier.append(p)
        return result

    def join(self, a: SimpleType, b: SimpleType) -> SimpleType:
        """Least upper bound via lowest common ancestor."""
        if a == b:
            return a
        if a == self.BOTTOM:
            return b
        if b == self.BOTTOM:
            return a
        if a == self.ANY or b == self.ANY:
            return self.ANY

        # BFS upward from a; first node also in ancestors(b) is the LCA.
        anc_b = self._ancestors(b)
        parents = self._get_parents()
        frontier = [a]
        visited = {a}
        while frontier:
            cur = frontier.pop(0)
            if cur in anc_b:
                return cur
            for p in parents.get(cur, {self.ANY}):
                if p not in visited:
                    visited.add(p)
                    frontier.append(p)

        return self.ANY

    def meet(self, a: SimpleType, b: SimpleType) -> SimpleType:
        """Greatest lower bound."""
        if a == b:
            return a
        if a == self.ANY:
            return b
        if b == self.ANY:
            return a
        if a == self.BOTTOM or b == self.BOTTOM:
            return self.BOTTOM

        # If one is ancestor of the other, return the lower one
        if b in self._ancestors(a):
            return a
        if a in self._ancestors(b):
            return b

        # Incompatible types
        return self.BOTTOM
    
    def leq(self, a: SimpleType, b: SimpleType) -> bool:
        """Lattice ordering: a ⊑ b."""
        return self.join(a, b) == b
    
    def from_value(self, value) -> SimpleType:
        """Infer type from a Python value."""
        if value is None:
            return self.NONE
        if isinstance(value, bool):
            return self.BOOL
        if isinstance(value, int):
            return self.INT
        if isinstance(value, float):
            return self.FLOAT
        if isinstance(value, str):
            return self.STR
        if isinstance(value, bytes):
            return self.BYTES
        if isinstance(value, list):
            return self.LIST
        if isinstance(value, tuple):
            return self.TUPLE
        if isinstance(value, dict):
            return self.DICT
        if isinstance(value, set):
            return self.SET
        if isinstance(value, type):
            return self.TYPE
        import types
        if isinstance(value, types.ModuleType):
            return self.MODULE
        if callable(value):
            return self.CALLABLE
        return self.ANY
    
    def from_annotation(self, ann) -> SimpleType:
        """Convert a type annotation to our lattice."""
        if ann is None:
            return self.ANY
        
        # Handle string annotations
        if isinstance(ann, str):
            name = ann.lower()
            mapping = {
                'int': self.INT,
                'float': self.FLOAT,
                'str': self.STR,
                'bool': self.BOOL,
                'bytes': self.BYTES,
                'none': self.NONE,
                'list': self.LIST,
                'dict': self.DICT,
                'tuple': self.TUPLE,
                'set': self.SET,
            }
            return mapping.get(name, self.ANY)
        
        # Handle type objects
        if ann is int:
            return self.INT
        if ann is float:
            return self.FLOAT
        if ann is str:
            return self.STR
        if ann is bool:
            return self.BOOL
        if ann is bytes:
            return self.BYTES
        if ann is type(None):
            return self.NONE
        if ann is list:
            return self.LIST
        if ann is dict:
            return self.DICT
        if ann is tuple:
            return self.TUPLE
        if ann is set:
            return self.SET
        
        return self.ANY
