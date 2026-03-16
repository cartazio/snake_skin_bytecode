"""
Abstract interpretation infrastructure.

Provides:
- AnnotationLattice: abstract class for annotation domains
- AnnotatedValue: value paired with its annotation
- AbstractStack: stack of annotated values with join semantics
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeVar, Generic, List, Any, Optional

A = TypeVar("A")  # Annotation type parameter


class AnnotationLattice(ABC, Generic[A]):
    """
    Abstract domain for annotations.
    
    Must form a join-semilattice with finite height (or use widening).
    
    Lattice laws:
    - join is commutative: join(a, b) = join(b, a)
    - join is associative: join(a, join(b, c)) = join(join(a, b), c)
    - join is idempotent: join(a, a) = a
    - bottom is identity: join(bottom, a) = a
    - top is absorbing: join(top, a) = top
    """
    
    @abstractmethod
    def bottom(self) -> A:
        """Return the bottom element (⊥). Represents no information."""
        ...
    
    @abstractmethod
    def top(self) -> A:
        """Return the top element (⊤). Represents all possibilities."""
        ...
    
    @abstractmethod
    def join(self, a: A, b: A) -> A:
        """
        Least upper bound (⊔).
        
        Used at CFG merge points to combine information from
        different execution paths.
        """
        ...
    
    @abstractmethod
    def meet(self, a: A, b: A) -> A:
        """
        Greatest lower bound (⊓).
        
        Used for refinement / narrowing.
        """
        ...
    
    @abstractmethod
    def leq(self, a: A, b: A) -> bool:
        """
        Lattice ordering: a ⊑ b.
        
        Equivalently: join(a, b) == b
        """
        ...
    
    def widen(self, old: A, new: A) -> A:
        """
        Widening operator for infinite-height lattices.
        
        Default: just return join (may not terminate for infinite lattices).
        Override for domains like intervals.
        """
        return self.join(old, new)
    
    def narrow(self, old: A, new: A) -> A:
        """
        Narrowing operator to recover precision after widening.
        
        Default: return meet.
        """
        return self.meet(old, new)


@dataclass
class AnnotatedValue(Generic[A]):
    """
    A value paired with its abstract annotation.
    
    The value is the ANF expression (or symbolic name).
    The annotation is the abstract domain element.
    """
    value: Any        # ANF expression, variable name, or concrete value
    ann: A            # Annotation from the lattice
    
    def __repr__(self) -> str:
        return f"{self.value}:{self.ann}"
    
    def map_ann(self, f) -> AnnotatedValue[A]:
        """Apply a function to the annotation."""
        return AnnotatedValue(self.value, f(self.ann))


@dataclass
class AbstractStack(Generic[A]):
    """
    Stack of annotated values for abstract interpretation.
    
    Mirrors the concrete operand stack but carries annotations.
    Supports join at CFG merge points.
    """
    items: List[AnnotatedValue[A]] = field(default_factory=list)
    lattice: Optional[AnnotationLattice[A]] = None
    
    def __len__(self) -> int:
        return len(self.items)
    
    def push(self, v: AnnotatedValue[A]) -> None:
        """Push an annotated value onto the stack."""
        self.items.append(v)
    
    def pop(self) -> AnnotatedValue[A]:
        """Pop and return the top annotated value."""
        if not self.items:
            raise IndexError("pop from empty abstract stack")
        return self.items.pop()
    
    def peek(self) -> AnnotatedValue[A]:
        """Return top without popping."""
        if not self.items:
            raise IndexError("peek at empty abstract stack")
        return self.items[-1]
    
    def pop_n(self, n: int) -> List[AnnotatedValue[A]]:
        """Pop n values, return in original push order (bottom to top)."""
        if n > len(self.items):
            raise IndexError(f"cannot pop {n} from stack of depth {len(self.items)}")
        if n == 0:
            return []
        result = self.items[-n:]
        self.items = self.items[:-n]
        return result
    
    def dup(self) -> None:
        """Duplicate the top of stack."""
        self.items.append(self.items[-1])
    
    def rot_n(self, n: int) -> None:
        """Rotate top n items: [a, b, c] -> [b, c, a] for n=3."""
        if n < 2:
            return
        top_n = self.items[-n:]
        self.items = self.items[:-n] + [top_n[-1]] + top_n[:-1]
    
    def copy(self) -> AbstractStack[A]:
        """Create a shallow copy of the stack."""
        return AbstractStack(list(self.items), self.lattice)
    
    def join_with(self, other: AbstractStack[A]) -> AbstractStack[A]:
        """
        Join two stacks at a CFG merge point.
        
        Requires same depth. Joins annotations element-wise.
        Values become phi nodes.
        """
        if len(self.items) != len(other.items):
            raise ValueError(
                f"Stack depth mismatch at join: {len(self.items)} vs {len(other.items)}"
            )
        
        if self.lattice is None:
            raise ValueError("Cannot join without a lattice")
        
        joined = []
        for a, b in zip(self.items, other.items):
            joined_ann = self.lattice.join(a.ann, b.ann)
            # Create phi node representation
            if a.value == b.value:
                phi_value = a.value
            else:
                phi_value = f"φ({a.value}, {b.value})"
            joined.append(AnnotatedValue(phi_value, joined_ann))
        
        return AbstractStack(joined, self.lattice)
    
    def __repr__(self) -> str:
        items_str = ", ".join(repr(v) for v in self.items)
        return f"[{items_str}]"
