# pyright: strict
"""Opcode regressions exposed by representative phase-the-first functions."""

from collections.abc import Callable
from typing import Protocol

from bytecode_anf import ANFCall, ANFPrim, StackToANF


class _HasValue(Protocol):
    value: object


def test_store_attr_preserves_receiver_then_value_order() -> None:
    def assign(obj: _HasValue, value: object) -> None:
        obj.value = value

    bindings, _ = StackToANF(assign.__code__).process()
    store = next(
        binding.rhs
        for binding in bindings
        if isinstance(binding.rhs, ANFPrim) and binding.rhs.op == "setattr"
    )

    assert [repr(argument) for argument in store.args] == ["obj", "'value'", "value"]


def test_compare_op_uses_disassembled_relation() -> None:
    def less_than_or_equal(left: int, right: int) -> bool:
        return left <= right

    bindings, _ = StackToANF(less_than_or_equal.__code__).process()
    comparisons = [
        binding.rhs.op
        for binding in bindings
        if isinstance(binding.rhs, ANFPrim) and binding.rhs.op.startswith("cmp:")
    ]

    assert comparisons == ["cmp:<="]


def test_python_312_kw_names_reach_anf_call() -> None:
    def invoke(function: Callable[..., object], value: object, dtype: object) -> object:
        return function(value, dtype=dtype)

    bindings, _ = StackToANF(invoke.__code__).process()
    call = next(binding.rhs for binding in bindings if isinstance(binding.rhs, ANFCall))
    unknown = [
        binding.rhs.op
        for binding in bindings
        if isinstance(binding.rhs, ANFPrim) and binding.rhs.op.startswith("?")
    ]

    assert [repr(argument) for argument in call.args] == ["value"]
    assert call.kwargs is not None
    assert [(keyword.name, repr(keyword.value)) for keyword in call.kwargs] == [
        ("dtype", "dtype")
    ]
    assert unknown == []
