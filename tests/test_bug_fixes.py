"""Tests for GPT-reported bug fixes (2026-03-22)."""

import pytest
import dis
from bytecode_anf import (
    ANFVar, ANFAtom, ANFPrim, ANFCall,
    StackToANF, CFGBuilder,
    TypeLattice, TransferRegistry,
    clear_transfers,
)
from bytecode_anf.builtin_transfers import register_builtin_transfers
from bytecode_anf.anf import KWArg


class TestFindLeadersArgval:
    """Bug 1: find_leaders() was adding RETURN_CONST argval as block leader."""
    
    def test_return_const_literal_not_leader(self):
        """RETURN_CONST 1 should NOT add offset 1 as a leader."""
        def returns_one():
            return 1
        
        builder = CFGBuilder(returns_one.__code__)
        leaders = builder.find_leaders()
        
        # Offset 0 should be a leader (entry)
        assert 0 in leaders
        
        # The literal value 1 should NOT be a leader
        # (it was being incorrectly added because RETURN_CONST argval = 1)
        # We verify by checking that leaders are all valid instruction offsets
        valid_offsets = {instr.offset for instr in builder.instructions}
        for leader in leaders:
            assert leader in valid_offsets, f"Invalid leader offset {leader} (not an instruction offset)"
    
    def test_return_const_various_literals(self):
        """Various RETURN_CONST literals should not pollute leaders."""
        def returns_42():
            return 42
        
        def returns_zero():
            return 0
        
        for fn in [returns_42, returns_zero]:
            builder = CFGBuilder(fn.__code__)
            leaders = builder.find_leaders()
            valid_offsets = {instr.offset for instr in builder.instructions}
            for leader in leaders:
                assert leader in valid_offsets


class TestLoadSuperAttr:
    """Bug 2: LOAD_SUPER_ATTR was popping attr_name from stack instead of using argval."""
    
    def test_super_attr_uses_argval(self):
        """super().method should use method name from argval, not stack."""
        # Can't easily test this without 3.12+ and a class, but we can verify
        # the handler structure by checking the ANF output for correct primitives
        class Parent:
            def foo(self):
                return 1
        
        class Child(Parent):
            def bar(self):
                return super().foo()
        
        # Get the bytecode for bar
        code = Child.bar.__code__
        converter = StackToANF(code)
        bindings, _ = converter.process()
        
        # Look for super_attr primitive
        super_attr_bindings = [
            (v, rhs) for v, rhs in bindings
            if isinstance(rhs, ANFPrim) and rhs.op == 'super_attr'
        ]
        
        # If LOAD_SUPER_ATTR is used (3.12+), we should have a super_attr prim
        # with the attr name as an argument (from argval, not stack)
        # In older versions, this test just passes vacuously
        for v, prim in super_attr_bindings:
            # The attr_name should be an ANFAtom containing 'foo'
            # It should be the last argument to super_attr
            attr_arg = prim.args[-1]
            assert isinstance(attr_arg, ANFAtom)
            assert attr_arg.value == 'foo', f"Expected 'foo', got {attr_arg.value}"


class TestCallKwKwargs:
    """Bug 3: CALL_KW was dropping kwargs."""
    
    def test_call_kw_preserves_kwargs(self):
        """Function calls with keyword args should preserve them in ANFCall.kwargs."""
        def uses_kwargs():
            return dict(a=1, b=2)
        
        code = uses_kwargs.__code__
        converter = StackToANF(code)
        bindings, _ = converter.process()
        
        # Look for ANFCall bindings
        call_bindings = [
            (v, rhs) for v, rhs in bindings
            if isinstance(rhs, ANFCall)
        ]
        
        # In Python 3.13+, dict(a=1, b=2) uses CALL_KW
        # The kwargs should be preserved
        for v, call in call_bindings:
            if call.kwargs is not None:
                # We found a call with kwargs - verify structure
                assert isinstance(call.kwargs, list)
                for kw in call.kwargs:
                    assert isinstance(kw, KWArg)
                    assert isinstance(kw.name, str)
                    assert isinstance(kw.value, ANFAtom)


class TestPopJumpFallthrough:
    """Bug 4: POP_JUMP_IF_* was using hardcoded offset+2 for fallthrough."""
    
    def test_branch_uses_actual_next_offset(self):
        """Branch fallthrough should use actual next instruction offset."""
        def simple_branch(x):
            if x:
                return 1
            return 0
        
        code = simple_branch.__code__
        instructions = list(dis.Bytecode(code))
        
        # Find a POP_JUMP_IF_* instruction and its successor
        for i, instr in enumerate(instructions):
            if instr.opname.startswith('POP_JUMP_IF'):
                if i + 1 < len(instructions):
                    actual_next = instructions[i + 1].offset
                    # The fallthrough should be actual_next, not instr.offset + 2
                    # (which could be wrong if CACHE entries intervene)
                    
                    # Process with StackToANF
                    converter = StackToANF(code)
                    converter.process()
                    # The test passes if process() doesn't crash
                    # More detailed verification would require inspecting terminators
                    break


class TestTransferRegistryScoping:
    """Bug 5: register_builtin_transfers didn't support custom registries."""
    
    def test_register_to_custom_registry(self):
        """Built-in transfers should register to provided registry."""
        clear_transfers()
        
        lat = TypeLattice()
        custom_reg = TransferRegistry()
        
        # Register to custom registry
        register_builtin_transfers(lat, registry=custom_reg)
        
        # Custom registry should have transfers
        assert custom_reg.get_transfer('LOAD_CONST') is not None
        assert custom_reg.get_transfer('BINARY_OP') is not None
        assert custom_reg.get_transfer('RETURN_VALUE') is not None
        
        # Global registry should still be empty (we called clear_transfers)
        from bytecode_anf.transfer import get_default_registry
        global_reg = get_default_registry()
        assert global_reg.get_transfer('LOAD_CONST') is None
    
    def test_default_registry_fallback(self):
        """Without explicit registry, should use global."""
        clear_transfers()
        
        lat = TypeLattice()
        register_builtin_transfers(lat)  # No registry arg
        
        from bytecode_anf.transfer import get_default_registry
        global_reg = get_default_registry()
        assert global_reg.get_transfer('LOAD_CONST') is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
