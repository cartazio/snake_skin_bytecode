"""Strict frontend behavior and permissive-mode compatibility."""

from types import SimpleNamespace

import pytest

from bytecode_anf import (
    ANFAtom,
    ANFBinding,
    ANFCall,
    ANFPrim,
    ANFVar,
    AbstractInterpreter,
    AnnotatedValue,
    FixpointLimitError,
    IRInvariantError,
    KWArg,
    StackMergeError,
    StackOverflowError,
    StackToANF,
    StackUnderflowError,
    TransferFailureError,
    TransferRegistry,
    TypeLattice,
    UnsupportedCallError,
    UnsupportedOpcodeError,
    bytecode_to_anf,
    bytecode_to_anf_cfg,
)
from bytecode_anf.builtin_transfers import register_builtin_transfers


def instruction(
    opname: str,
    *,
    arg: int | None = None,
    argval: object = None,
    offset: int = 42,
) -> SimpleNamespace:
    return SimpleNamespace(
        opname=opname,
        arg=arg,
        argval=argval,
        offset=offset,
    )


def type_registry(lattice: TypeLattice) -> TransferRegistry:
    registry = TransferRegistry()
    register_builtin_transfers(lattice, registry=registry)
    return registry


class TestStrictANFConversion:
    def test_unknown_opcode_is_typed_error(self):
        converter = StackToANF()
        unknown = instruction("FUTURE_OPCODE", arg=7, argval=7)

        with pytest.raises(UnsupportedOpcodeError) as raised:
            converter.step(unknown)

        assert raised.value.opname == "FUTURE_OPCODE"
        assert raised.value.offset == 42

    def test_unknown_call_form_is_distinct_error(self):
        converter = StackToANF(strict=True)

        with pytest.raises(UnsupportedCallError):
            converter.step(instruction("CALL_FUTURE", arg=0, argval=0))

    def test_permissive_unknown_opcode_keeps_placeholder(self):
        converter = StackToANF(strict=False)
        converter.step(instruction("FUTURE_OPCODE", arg=7, argval=7))

        binding = converter.bindings[-1]
        assert isinstance(binding, ANFBinding)
        assert isinstance(binding.rhs, ANFPrim)
        assert binding.rhs.op == "?FUTURE_OPCODE"

    def test_stack_underflow_has_instruction_site(self):
        converter = StackToANF(strict=True)
        returning = instruction("RETURN_VALUE", offset=8)

        with pytest.raises(StackUnderflowError) as raised:
            converter.step(returning)

        assert raised.value.opname == "RETURN_VALUE"
        assert raised.value.offset == 8

    def test_invalid_ir_operand_is_rejected(self):
        converter = StackToANF(strict=True)

        with pytest.raises(IRInvariantError):
            converter.emit(
                ANFVar("x"),
                ANFPrim("bad", [object()]),  # type: ignore[list-item]
            )

    def test_invalid_keyword_argument_shape_is_rejected(self):
        converter = StackToANF(strict=True)

        with pytest.raises(IRInvariantError):
            converter.emit(
                ANFVar("x"),
                ANFCall(
                    ANFAtom("function"),
                    [],
                    kwargs=[object()],  # type: ignore[list-item]
                ),
            )

    def test_strict_straight_line_conversion_returns_bindings(self):
        def add_one(x):
            y = x + 1
            return y

        bindings = bytecode_to_anf(add_one.__code__, strict=True)

        assert bindings
        assert all(isinstance(binding, ANFBinding) for binding in bindings)
        # Compatibility during the tuple-to-node migration.
        first_var, first_rhs = bindings[0]
        assert bindings[0][0] == first_var
        assert bindings[0][1] == first_rhs

    def test_call_spread_is_explicitly_unsupported(self):
        def spread_call(function, args):
            return function(*args)

        with pytest.raises(UnsupportedCallError) as raised:
            bytecode_to_anf(spread_call.__code__)

        assert raised.value.opname == "CALL_FUNCTION_EX"

    def test_keyword_call_preserves_names(self):
        def keyword_call(function, value):
            return function(value, enabled=True)

        bindings = bytecode_to_anf(keyword_call.__code__, strict=True)
        calls = [
            binding.rhs for binding in bindings if isinstance(binding.rhs, ANFCall)
        ]

        assert len(calls) == 1
        assert calls[0].kwargs == [KWArg("enabled", ANFAtom(True))]

    def test_strict_cfg_accepts_an_exact_branch(self):
        def choose(condition, x, y):
            if condition:
                result = x
            else:
                result = y
            answer = result + 1
            return answer

        with pytest.raises(UnsupportedOpcodeError):
            bytecode_to_anf(choose.__code__)

        blocks = bytecode_to_anf_cfg(choose.__code__)

        assert len(blocks) >= 3
        assert all(
            not (isinstance(binding.rhs, ANFPrim) and binding.rhs.op.startswith("?"))
            for block in blocks.values()
            for binding in block.bindings
        )


class TestStrictAbstractInterpretation:
    def test_exact_program_analyzes_without_warnings(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)
        interpreter = AbstractInterpreter(lattice, registry=registry)

        def add_one(x):
            return x + 1

        result = interpreter.analyze(
            add_one.__code__,
            initial_locals={"x": lattice.INT},
        )

        assert result.return_ann == lattice.INT
        assert result.warnings == []

    def test_keyword_call_analyzes_without_dropping_stack_state(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)
        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def keyword_call(function, value):
            return function(value, enabled=True)

        result = interpreter.analyze(
            keyword_call.__code__,
            initial_locals={"function": lattice.CALLABLE, "value": lattice.INT},
        )

        assert result.return_ann == lattice.ANY
        assert result.warnings == []

    def test_linear_analysis_rejects_control_flow(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)
        interpreter = AbstractInterpreter(lattice, registry=registry)

        def choose(condition, left, right):
            return left if condition else right

        with pytest.raises(UnsupportedOpcodeError):
            interpreter.analyze(choose.__code__)

        cfg_result = interpreter.analyze_cfg_detailed(choose.__code__)
        assert cfg_result.entry_states

    def test_missing_transfer_is_typed_error(self):
        lattice = TypeLattice()
        interpreter = AbstractInterpreter(
            lattice,
            registry=TransferRegistry(),
        )

        def identity(x):
            return x

        with pytest.raises(UnsupportedOpcodeError) as raised:
            interpreter.analyze(identity.__code__)

        assert raised.value.opname == "RESUME"

    def test_transfer_exception_is_typed_and_chained(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)

        @registry.annotates("BINARY_OP")
        def explode(stack, instr, **context):
            raise RuntimeError("broken transfer")

        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def add_one(x):
            return x + 1

        with pytest.raises(TransferFailureError) as raised:
            interpreter.analyze(
                add_one.__code__,
                initial_locals={"x": lattice.INT},
            )

        assert raised.value.opname == "BINARY_OP"
        assert isinstance(raised.value.__cause__, RuntimeError)

    def test_cfg_transfer_exception_is_not_swallowed(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)

        @registry.annotates("BINARY_OP")
        def explode(stack, instr, **context):
            raise RuntimeError("broken CFG transfer")

        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def add_one(x):
            return x + 1

        with pytest.raises(TransferFailureError):
            interpreter.analyze_cfg_detailed(add_one.__code__)

    def test_transfer_stack_underflow_is_typed(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)

        @registry.annotates("LOAD_CONST")
        def underflow(stack, instr, **context):
            stack.pop_n(2)

        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def add_one(x):
            return x + 1

        with pytest.raises(StackUnderflowError) as raised:
            interpreter.analyze(add_one.__code__)

        assert raised.value.opname == "LOAD_CONST"

    def test_transfer_stack_overflow_is_typed(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)

        @registry.annotates("RESUME")
        def overflow(stack, instr, code, **context):
            for index in range(code.co_stacksize + 1):
                stack.push(AnnotatedValue(index, lattice.ANY))

        interpreter = AbstractInterpreter(lattice, registry=registry)

        def identity(x):
            return x

        with pytest.raises(StackOverflowError) as raised:
            interpreter.analyze(identity.__code__)

        assert raised.value.opname == "RESUME"

    def test_invalid_transfer_result_is_rejected(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)

        @registry.annotates("RESUME")
        def invalid_result(stack, instr, **context):
            return "not a transfer result"

        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def identity(x):
            return x

        with pytest.raises(TransferFailureError) as raised:
            interpreter.analyze(identity.__code__)

        assert raised.value.opname == "RESUME"

    def test_missing_call_transfer_is_call_error(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)
        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def spread_call(function, args):
            return function(*args)

        with pytest.raises(UnsupportedCallError) as raised:
            interpreter.analyze(spread_call.__code__)

        assert raised.value.opname == "CALL_FUNCTION_EX"

    def test_cfg_stack_mismatch_is_typed(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)
        ordinary_load = registry.get_transfer("LOAD_FAST")
        assert ordinary_load is not None

        @registry.annotates("LOAD_FAST")
        def uneven_load(stack, instr, **context):
            ordinary_load(stack, instr, **context)
            if instr.argval == "x":
                stack.push(AnnotatedValue("extra", lattice.ANY))

        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def choose(condition, x, y):
            if condition:
                result = x
            else:
                result = y
            answer = result + 1
            return answer

        with pytest.raises(StackMergeError):
            interpreter.analyze_cfg_detailed(choose.__code__)

    def test_cfg_iteration_limit_is_not_reported_as_success(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)
        interpreter = AbstractInterpreter(lattice, registry=registry, strict=True)

        def identity(x):
            return x

        with pytest.raises(FixpointLimitError):
            interpreter.analyze_cfg_detailed(identity.__code__, max_iterations=0)

    def test_permissive_transfer_failure_is_a_warning(self):
        lattice = TypeLattice()
        registry = type_registry(lattice)

        @registry.annotates("BINARY_OP")
        def explode(stack, instr, **context):
            raise RuntimeError("broken transfer")

        interpreter = AbstractInterpreter(lattice, registry=registry, strict=False)

        def add_one(x):
            return x + 1

        result = interpreter.analyze(
            add_one.__code__,
            initial_locals={"x": lattice.INT},
        )

        assert any("BINARY_OP" in warning for warning in result.warnings)


def test_anf_binding_rejects_non_atomic_strict_call_argument():
    converter = StackToANF(strict=True)
    bad_rhs = ANFCall(
        ANFAtom("function"),
        [object()],  # type: ignore[list-item]
    )

    with pytest.raises(IRInvariantError):
        converter.emit(ANFVar("result"), bad_rhs)
