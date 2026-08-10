"""
Abstract interpreter for bytecode with annotation flow.

Combines:
1. Stack simulation (Danvy's stack <-> ANF correspondence)
2. Abstract interpretation (Cousot & Cousot's fixpoint framework)
3. Transfer function dispatch (@annotates DSL)
"""

from __future__ import annotations
import dis
from dataclasses import dataclass
from typing import TypeVar, Generic, Dict, List, Tuple, Optional, Any, Set, cast
from types import CodeType

from .lattice import AnnotationLattice, AnnotatedValue, AbstractStack
from .transfer import TransferRegistry, get_default_registry
from .stack_to_anf import CFGBuilder
from .errors import (
    FixpointLimitError,
    FrontendError,
    IRInvariantError,
    StackMergeError,
    StackOverflowError,
    StackUnderflowError,
    TransferFailureError,
    UnsupportedOpcodeError,
    unsupported_instruction_error,
)

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
        for left_value, right_value in zip(self.stack.items, other.stack.items):
            if not (
                lattice.leq(left_value.ann, right_value.ann)
                and lattice.leq(right_value.ann, left_value.ann)
            ):
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


@dataclass
class CFGAnalysisResult(Generic[A]):
    """Detailed CFG analysis result with joined and per-edge state."""
    entry_states: Dict[int, AnalysisState[A]]
    exit_states: Dict[int, AnalysisState[A]]
    predecessor_states: Dict[int, Dict[int, AnalysisState[A]]]


class AbstractInterpreter(Generic[A]):
    """
    Abstract interpreter for Python bytecode.

    Propagates annotations through the control flow graph
    using transfer functions from a TransferRegistry.

    Strict analysis is the default. Pass ``strict=False`` only when warnings
    and incomplete transfer coverage are acceptable exploratory output.
    """

    def __init__(
        self,
        lattice: AnnotationLattice[A],
        registry: Optional[TransferRegistry] = None,
        *,
        strict: bool = True,
    ):
        self.lattice = lattice
        self.registry = registry or get_default_registry()
        self.strict = strict

    def _invoke_transfer(
        self,
        stack: AbstractStack[A],
        instruction: Any,
        *,
        locals_ann: Dict[str, A],
        code: CodeType,
    ) -> Any:
        transfer = self.registry.get_transfer(instruction.opname)
        if transfer is None:
            if self.strict:
                raise unsupported_instruction_error(
                    instruction,
                    f"no abstract transfer registered for {instruction.opname}",
                )
            return None

        try:
            result = transfer(
                stack,
                instruction,
                locals_ann=locals_ann,
                lattice=self.lattice,
                code=code,
                strict=self.strict,
            )
        except FrontendError:
            raise
        except IndexError as error:
            if self.strict:
                raise StackUnderflowError(
                    f"abstract transfer underflowed the stack: {error}",
                    instruction=instruction,
                ) from error
            raise
        except Exception as error:
            if self.strict:
                raise TransferFailureError(
                    f"abstract transfer failed with {type(error).__name__}: {error}",
                    instruction=instruction,
                ) from error
            raise

        if self.strict and not all(
            isinstance(value, AnnotatedValue) for value in stack.items
        ):
            raise IRInvariantError(
                "abstract transfer put a non-AnnotatedValue on the stack",
                instruction=instruction,
            )
        if self.strict and len(stack) > code.co_stacksize:
            raise StackOverflowError(
                f"abstract depth {len(stack)} exceeds co_stacksize {code.co_stacksize}",
                instruction=instruction,
            )
        return result

    def _read_return_result(self, result: Any, instruction: Any) -> Optional[A]:
        if result is None:
            return None
        if (
            not isinstance(result, tuple)
            or len(result) != 3
            or result[0] != "return"
        ):
            if self.strict:
                raise TransferFailureError(
                    "transfer result must be None or ('return', value, annotation)",
                    instruction=instruction,
                )
            return None
        return cast(A, result[2])

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
        if self.strict and len(CFGBuilder(code).build()) > 1:
            control_transfer = next(
                (
                    instruction
                    for instruction in instructions
                    if instruction.opname in CFGBuilder.JUMPS
                ),
                None,
            )
            raise UnsupportedOpcodeError(
                "linear abstract interpretation cannot represent control flow; "
                "use analyze_cfg() or analyze_cfg_detailed()",
                instruction=control_transfer,
            )

        for instr in instructions:
            try:
                result = self._invoke_transfer(
                    stack,
                    instr,
                    locals_ann=locals_ann,
                    code=code,
                )
                returned_ann = self._read_return_result(result, instr)
                if returned_ann is not None:
                    if return_ann is None:
                        return_ann = returned_ann
                    else:
                        return_ann = self.lattice.join(return_ann, returned_ann)
            except FrontendError as error:
                if self.strict:
                    raise
                warnings.append(
                    f"{instr.opname} at offset {instr.offset}: {error}"
                )
            except Exception as error:
                if self.strict:
                    raise TransferFailureError(
                        f"analysis step failed with {type(error).__name__}: {error}",
                        instruction=instr,
                    ) from error
                warnings.append(
                    f"{instr.opname} at offset {instr.offset}: {error}"
                )

            if trace:
                stack_state = [f"{v.value}:{v.ann}" for v in stack.items]
                trace_log.append((instr.opname, stack_state))

        return AnalysisResult(
            trace=trace_log,
            locals_ann=locals_ann,
            return_ann=return_ann,
            warnings=warnings
        )

    def analyze_cfg_detailed(
        self,
        code: CodeType,
        initial_locals: Optional[Dict[str, A]] = None,
        max_iterations: int = 100
    ) -> CFGAnalysisResult[A]:
        """
        Analyze with full CFG awareness using worklist algorithm.

        Preserves both the joined state at each block entry and the
        per-predecessor exit state flowing into each successor.
        """
        cfg_builder = CFGBuilder(code)
        blocks = cfg_builder.build()

        if not blocks:
            return CFGAnalysisResult(entry_states={}, exit_states={}, predecessor_states={})

        sorted_labels = sorted(blocks.keys())
        block_ranges: Dict[int, Tuple[int, int]] = {}
        for i, label in enumerate(sorted_labels):
            start = label
            end = sorted_labels[i + 1] if i + 1 < len(sorted_labels) else 2**31
            block_ranges[label] = (start, end)

        init_state = AnalysisState(
            stack=AbstractStack(lattice=self.lattice),
            locals_ann=dict(initial_locals or {})
        )

        instructions = list(dis.Bytecode(code))
        entry_states: Dict[int, AnalysisState[A]] = {0: init_state}
        exit_states: Dict[int, AnalysisState[A]] = {}
        predecessor_states: Dict[int, Dict[int, AnalysisState[A]]] = {}

        worklist: Set[int] = {0}
        iterations = 0

        while worklist and iterations < max_iterations:
            iterations += 1
            label = min(worklist)
            worklist.remove(label)

            block = blocks[label]
            state = entry_states[label].copy()

            start, end = block_ranges[label]
            block_instructions = [
                instr for instr in instructions
                if start <= instr.offset < end
            ]

            for instr in block_instructions:
                try:
                    result = self._invoke_transfer(
                        state.stack,
                        instr,
                        locals_ann=state.locals_ann,
                        code=code,
                    )
                    self._read_return_result(result, instr)
                except FrontendError:
                    if self.strict:
                        raise
                except Exception as error:
                    if self.strict:
                        raise TransferFailureError(
                            "CFG analysis step failed with "
                            f"{type(error).__name__}: {error}",
                            instruction=instr,
                        ) from error

            exit_states[label] = state.copy()

            for succ_label in block.successors:
                predecessor_states.setdefault(succ_label, {})[label] = state.copy()

                pred_inputs = predecessor_states[succ_label].values()
                pred_iter = iter(pred_inputs)
                joined = next(pred_iter).copy()
                for pred_state in pred_iter:
                    try:
                        joined = joined.join_with(pred_state, self.lattice)
                    except ValueError as error:
                        if self.strict:
                            raise StackMergeError(
                                f"cannot join predecessor states for B{succ_label}: {error}"
                            ) from error
                        raise

                old_state = entry_states.get(succ_label)
                if old_state is None or not joined.equals(old_state, self.lattice):
                    entry_states[succ_label] = joined
                    worklist.add(succ_label)

        if self.strict and worklist:
            pending = ", ".join(f"B{label}" for label in sorted(worklist))
            raise FixpointLimitError(
                f"CFG worklist did not converge in {max_iterations} steps; pending {pending}"
            )

        return CFGAnalysisResult(
            entry_states=entry_states,
            exit_states=exit_states,
            predecessor_states=predecessor_states,
        )

    def analyze_cfg(
        self,
        code: CodeType,
        initial_locals: Optional[Dict[str, A]] = None,
        max_iterations: int = 100
    ) -> Dict[int, AnalysisState[A]]:
        """Backward-compatible wrapper returning joined block-entry states."""
        return self.analyze_cfg_detailed(
            code,
            initial_locals=initial_locals,
            max_iterations=max_iterations,
        ).entry_states
