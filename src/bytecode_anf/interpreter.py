"""
Abstract interpreter for bytecode with annotation flow.

Combines:
1. Stack simulation (Danvy's stack <-> ANF correspondence)
2. Abstract interpretation (Cousot & Cousot's fixpoint framework)
3. Transfer function dispatch (@annotates DSL)
"""

from __future__ import annotations
import dis
from dataclasses import dataclass, field
from typing import TypeVar, Generic, Dict, List, Tuple, Optional, Any, Set
from types import CodeType

from .lattice import AnnotationLattice, AnnotatedValue, AbstractStack
from .transfer import get_transfer, TransferRegistry, get_default_registry
from .stack_to_anf import CFGBuilder, BasicBlock

A = TypeVar("A")  # Annotation type


@dataclass
class AnalysisState(Generic[A]):
    """State of the analysis at a program point."""
    stack: AbstractStack[A]
    locals_ann: Dict[str, A]

    def copy(self) -> AnalysisState[A]:
        return AnalysisState(
            stack=self.stack.copy(),
            locals_ann=dict(self.locals_ann)
        )

    def join_with(self, other: AnalysisState[A], lattice: AnnotationLattice[A]) -> AnalysisState[A]:
        """Join two states at a merge point."""
        joined_stack = self.stack.join_with(other.stack)
        joined_locals = {}
        all_keys = set(self.locals_ann.keys()) | set(other.locals_ann.keys())
        for k in all_keys:
            a = self.locals_ann.get(k, lattice.bottom())
            b = other.locals_ann.get(k, lattice.bottom())
            joined_locals[k] = lattice.join(a, b)
        return AnalysisState(joined_stack, joined_locals)

    def equals(self, other: AnalysisState[A], lattice: AnnotationLattice[A]) -> bool:
        """Lattice-aware equality check for fixpoint detection."""
        # Check locals
        all_keys = set(self.locals_ann.keys()) | set(other.locals_ann.keys())
        for k in all_keys:
            a = self.locals_ann.get(k, lattice.bottom())
            b = other.locals_ann.get(k, lattice.bottom())
            if not (lattice.leq(a, b) and lattice.leq(b, a)):
                return False
        # Check stacks
        if len(self.stack) != len(other.stack):
            return False
        for a, b in zip(self.stack.items, other.stack.items):
            if not (lattice.leq(a.ann, b.ann) and lattice.leq(b.ann, a.ann)):
                return False
        return True


@dataclass
class AnalysisResult(Generic[A]):
    """Result of analyzing a function."""
    # Per-instruction trace: (opname, stack_state_after)
    trace: List[Tuple[str, List[str]]]
    # Final annotation for each local variable
    locals_ann: Dict[str, A]
    # Return value annotation (if determinable)
    return_ann: Optional[A]
    # Warnings or issues encountered
    warnings: List[str]


class AbstractInterpreter(Generic[A]):
    """
    Abstract interpreter for Python bytecode.

    Propagates annotations through the control flow graph
    using transfer functions from a TransferRegistry.
    """

    def __init__(self, lattice: AnnotationLattice[A],
                 registry: Optional[TransferRegistry] = None):
        self.lattice = lattice
        self.registry = registry or get_default_registry()

    def analyze(
        self,
        code: CodeType,
        initial_locals: Optional[Dict[str, A]] = None,
        trace: bool = True
    ) -> AnalysisResult[A]:
        """
        Analyze a code object (linear scan, no CFG awareness).

        Args:
            code: The code object to analyze
            initial_locals: Initial annotations for local variables
            trace: Whether to record per-instruction trace

        Returns:
            AnalysisResult with annotations and trace
        """
        stack = AbstractStack(lattice=self.lattice)
        locals_ann = dict(initial_locals or {})
        trace_log: List[Tuple[str, List[str]]] = []
        warnings: List[str] = []
        return_ann: Optional[A] = None

        instructions = list(dis.Bytecode(code))

        for instr in instructions:
            xfer = self.registry.get_transfer(instr.opname)

            if xfer is not None:
                try:
                    result = xfer(
                        stack, instr,
                        locals_ann=locals_ann,
                        lattice=self.lattice,
                        code=code
                    )
                    if result is not None:
                        if result[0] == 'return':
                            _, val, ann = result
                            if return_ann is None:
                                return_ann = ann
                            else:
                                return_ann = self.lattice.join(return_ann, ann)
                except Exception as e:
                    warnings.append(f"{instr.opname} at offset {instr.offset}: {e}")

            if trace:
                stack_state = [f"{v.value}:{v.ann}" for v in stack.items]
                trace_log.append((instr.opname, stack_state))

        return AnalysisResult(
            trace=trace_log,
            locals_ann=locals_ann,
            return_ann=return_ann,
            warnings=warnings
        )

    def analyze_cfg(
        self,
        code: CodeType,
        initial_locals: Optional[Dict[str, A]] = None,
        max_iterations: int = 100
    ) -> Dict[int, AnalysisState[A]]:
        """
        Analyze with full CFG awareness using worklist algorithm.

        Handles loops and branches correctly by computing
        a fixpoint over the CFG.
        """
        # Build CFG
        cfg_builder = CFGBuilder(code)
        blocks = cfg_builder.build()

        if not blocks:
            return {}

        # Precompute block ranges for O(1) instruction-to-block lookup
        sorted_labels = sorted(blocks.keys())
        block_ranges: Dict[int, Tuple[int, int]] = {}
        for i, label in enumerate(sorted_labels):
            start = label
            end = sorted_labels[i + 1] if i + 1 < len(sorted_labels) else 2**31
            block_ranges[label] = (start, end)

        # Initial state
        init_state = AnalysisState(
            stack=AbstractStack(lattice=self.lattice),
            locals_ann=dict(initial_locals or {})
        )

        # State at entry of each block
        entry_states: Dict[int, AnalysisState[A]] = {0: init_state}

        # Worklist
        worklist: Set[int] = {0}
        iterations = 0

        while worklist and iterations < max_iterations:
            iterations += 1
            label = min(worklist)
            worklist.remove(label)

            block = blocks[label]
            state = entry_states[label].copy()

            # Process instructions in this block
            start, end = block_ranges[label]
            instructions = [
                instr for instr in dis.Bytecode(code)
                if start <= instr.offset < end
            ]

            for instr in instructions:
                xfer = self.registry.get_transfer(instr.opname)
                if xfer is not None:
                    try:
                        xfer(
                            state.stack, instr,
                            locals_ann=state.locals_ann,
                            lattice=self.lattice,
                            code=code
                        )
                    except Exception:
                        pass

            # Propagate to successors
            for succ_label in block.successors:
                if succ_label not in entry_states:
                    entry_states[succ_label] = state.copy()
                    worklist.add(succ_label)
                else:
                    old_state = entry_states[succ_label]
                    new_state = old_state.join_with(state, self.lattice)

                    if not new_state.equals(old_state, self.lattice):
                        entry_states[succ_label] = new_state
                        worklist.add(succ_label)

        return entry_states
