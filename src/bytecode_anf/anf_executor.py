"""Concrete execution for CFG-shaped ANF, including explicit join invocation."""

from __future__ import annotations

import builtins
import operator
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .anf import (
    ANFAtom,
    ANFBody,
    ANFBranch,
    ANFCall,
    ANFInvokeJoin,
    ANFJoin,
    ANFJump,
    ANFPrim,
    ANFReturn,
    ANFTerminator,
    ANFVar,
)
from .stack_to_anf import BasicBlock


class ANFExecutionError(RuntimeError):
    """CFG-shaped ANF cannot be executed under the declared IR semantics."""


_MISSING = object()
_EXHAUSTED = object()


class _PeekableIterator:
    """Iterator with the lookahead required by lowered ``FOR_ITER``."""

    def __init__(self, iterator: Iterator[Any]) -> None:
        self._iterator = iterator
        self._cached: Any = _MISSING

    def has_next(self) -> bool:
        if self._cached is _EXHAUSTED:
            return False
        if self._cached is _MISSING:
            try:
                self._cached = next(self._iterator)
            except StopIteration:
                self._cached = _EXHAUSTED
                return False
        return True

    def take(self) -> Any:
        if not self.has_next():
            return _EXHAUSTED
        value = self._cached
        self._cached = _MISSING
        return value


_BINARY_OPERATIONS: dict[str, Callable[[Any, Any], Any]] = {
    "+": operator.add,
    "+=": operator.iadd,
    "-": operator.sub,
    "-=": operator.isub,
    "*": operator.mul,
    "*=": operator.imul,
    "/": operator.truediv,
    "/=": operator.itruediv,
    "//": operator.floordiv,
    "//=": operator.ifloordiv,
    "%": operator.mod,
    "%=": operator.imod,
    "**": operator.pow,
    "**=": operator.ipow,
    "&": operator.and_,
    "|": operator.or_,
    "^": operator.xor,
    "<<": operator.lshift,
    ">>": operator.rshift,
    "@": operator.matmul,
}

_COMPARISONS: dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
}


def _evaluate_atom(atom: ANFAtom, environment: Mapping[str, Any]) -> Any:
    if isinstance(atom.value, ANFVar):
        try:
            return environment[atom.value.name]
        except KeyError as error:
            raise ANFExecutionError(
                f"unbound ANF variable {atom.value.name}"
            ) from error
    return atom.value


def _evaluate_primitive(
    primitive: ANFPrim,
    environment: Mapping[str, Any],
    global_values: Mapping[str, Any],
) -> Any:
    arguments = [_evaluate_atom(argument, environment) for argument in primitive.args]
    operation = primitive.op

    binary = _BINARY_OPERATIONS.get(operation)
    if binary is not None and len(arguments) == 2:
        return binary(arguments[0], arguments[1])

    if operation.startswith("cmp:") and len(arguments) == 2:
        comparison = _COMPARISONS.get(operation.removeprefix("cmp:"))
        if comparison is None:
            raise ANFExecutionError(f"unsupported comparison {operation}")
        return comparison(arguments[0], arguments[1])

    if operation == "global" and len(arguments) == 1:
        name = arguments[0]
        if not isinstance(name, str):
            raise ANFExecutionError("global lookup requires a string name")
        if name in global_values:
            return global_values[name]
        try:
            return getattr(builtins, name)
        except AttributeError as error:
            raise ANFExecutionError(f"unknown global {name}") from error

    if operation == "iter" and len(arguments) == 1:
        return _PeekableIterator(iter(arguments[0]))
    if operation == "iter_has_next" and len(arguments) == 1:
        iterator = arguments[0]
        if not isinstance(iterator, _PeekableIterator):
            raise ANFExecutionError("iter_has_next requires a lowered iterator")
        return iterator.has_next()
    if operation == "next" and len(arguments) == 1:
        iterator = arguments[0]
        if not isinstance(iterator, _PeekableIterator):
            raise ANFExecutionError("next requires a lowered iterator")
        return iterator.take()
    if operation == "bool" and len(arguments) == 1:
        return bool(arguments[0])
    if operation == "is" and len(arguments) == 2:
        return arguments[0] is arguments[1]
    if operation == "is-not" and len(arguments) == 2:
        return arguments[0] is not arguments[1]
    if operation == "in" and len(arguments) == 2:
        return arguments[0] in arguments[1]
    if operation == "not-in" and len(arguments) == 2:
        return arguments[0] not in arguments[1]

    raise ANFExecutionError(f"unsupported ANF primitive {operation}")


def _evaluate_rhs(
    rhs: ANFAtom | ANFPrim | ANFCall | ANFJoin,
    environment: Mapping[str, Any],
    global_values: Mapping[str, Any],
) -> Any:
    if isinstance(rhs, ANFAtom):
        return _evaluate_atom(rhs, environment)
    if isinstance(rhs, ANFPrim):
        return _evaluate_primitive(rhs, environment, global_values)
    if isinstance(rhs, ANFCall):
        function = _evaluate_atom(rhs.func, environment)
        arguments = [_evaluate_atom(argument, environment) for argument in rhs.args]
        keywords = {
            keyword.name: _evaluate_atom(keyword.value, environment)
            for keyword in rhs.kwargs or []
        }
        if not callable(function):
            raise ANFExecutionError(f"ANF call target is not callable: {function!r}")
        return function(*arguments, **keywords)
    if isinstance(rhs, ANFJoin):
        return rhs
    raise ANFExecutionError(f"unsupported ANF right-hand side {type(rhs).__name__}")


def _execute_body(
    body: ANFBody,
    environment: dict[str, Any],
    global_values: Mapping[str, Any],
) -> ANFTerminator:
    for binding in body.bindings:
        environment[binding.var.name] = _evaluate_rhs(
            binding.rhs,
            environment,
            global_values,
        )
    if body.terminator is None:
        raise ANFExecutionError("join field body has no terminator")
    return body.terminator


def execute_anf_cfg(
    blocks: Mapping[int, BasicBlock],
    arguments: Mapping[str, Any],
    *,
    global_values: Mapping[str, Any] | None = None,
    max_steps: int = 10_000,
) -> Any:
    """Execute CFG-shaped ANF and return the value of its return terminator."""
    if not blocks:
        raise ANFExecutionError("cannot execute an empty ANF CFG")

    globals_environment = global_values or {}
    environment = dict(arguments)
    joins: dict[ANFVar, ANFJoin] = {}
    for block in blocks.values():
        for binding in block.bindings:
            if isinstance(binding.rhs, ANFJoin):
                if binding.var in joins:
                    raise ANFExecutionError(f"duplicate join definition {binding.var}")
                joins[binding.var] = binding.rhs

    current_label = 0 if 0 in blocks else min(blocks)
    pending_terminator: ANFTerminator | None = None

    for _ in range(max_steps):
        if pending_terminator is None:
            try:
                block = blocks[current_label]
            except KeyError as error:
                raise ANFExecutionError(
                    f"control transferred to missing block B{current_label}"
                ) from error
            for binding in block.bindings:
                if isinstance(binding.rhs, ANFJoin):
                    continue
                environment[binding.var.name] = _evaluate_rhs(
                    binding.rhs,
                    environment,
                    globals_environment,
                )
            pending_terminator = block.terminator
            if pending_terminator is None:
                raise ANFExecutionError(
                    f"executable block B{current_label} has no terminator"
                )

        if isinstance(pending_terminator, ANFReturn):
            return _evaluate_atom(pending_terminator.value, environment)
        if isinstance(pending_terminator, ANFBranch):
            condition = _evaluate_atom(pending_terminator.cond, environment)
            current_label = (
                pending_terminator.true_label
                if condition
                else pending_terminator.false_label
            )
            pending_terminator = None
            continue
        if isinstance(pending_terminator, ANFJump):
            current_label = pending_terminator.label
            pending_terminator = None
            continue
        if isinstance(pending_terminator, ANFInvokeJoin):
            try:
                join = joins[pending_terminator.join]
            except KeyError as error:
                raise ANFExecutionError(
                    f"invocation references undefined join {pending_terminator.join}"
                ) from error
            fields = [
                field
                for field in join.fields
                if field.label == pending_terminator.field_label
            ]
            if len(fields) != 1:
                raise ANFExecutionError(
                    f"join {join.name} has {len(fields)} fields for "
                    f"B{pending_terminator.field_label}"
                )
            field = fields[0]
            if len(field.params) != len(pending_terminator.args):
                raise ANFExecutionError(
                    f"join {join.name}.from_B{field.label} expects "
                    f"{len(field.params)} arguments but received "
                    f"{len(pending_terminator.args)}"
                )
            values = [
                _evaluate_atom(argument, environment)
                for argument in pending_terminator.args
            ]
            environment.update(
                (parameter.var.name, value)
                for parameter, value in zip(field.params, values)
            )
            pending_terminator = _execute_body(
                field.body,
                environment,
                globals_environment,
            )
            continue

        raise ANFExecutionError(
            f"unsupported ANF terminator {type(pending_terminator).__name__}"
        )

    raise ANFExecutionError(f"ANF execution exceeded {max_steps} control steps")
