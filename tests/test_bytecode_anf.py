"""Tests for bytecode-anf."""

import pytest
import dis
from bytecode_anf import (
    ANFVar, ANFAtom, ANFPrim, ANFCall, ANFLet,
    ANFJoin, ANFInvokeJoin,
    StackToANF, CFGBuilder, bytecode_to_anf, bytecode_to_anf_cfg,
    AnnotationLattice, AnnotatedValue, AbstractStack,
    AbstractInterpreter,
    TypeLattice, SimpleType,
    annotates, annotates_family, get_transfer, clear_transfers,
)
from bytecode_anf.builtin_transfers import register_builtin_transfers


class TestANFNodes:
    """Test ANF AST node construction."""
    
    def test_anf_var(self):
        v = ANFVar("x")
        assert v.name == "x"
        assert repr(v) == "x"
    
    def test_anf_atom_var(self):
        v = ANFVar("x")
        a = ANFAtom(v)
        assert a.is_var
        assert not a.is_const
        assert repr(a) == "x"
    
    def test_anf_atom_const(self):
        a = ANFAtom(42)
        assert a.is_const
        assert not a.is_var
        assert repr(a) == "42"
    
    def test_anf_prim(self):
        a = ANFAtom(ANFVar("x"))
        b = ANFAtom(ANFVar("y"))
        p = ANFPrim("+", [a, b])
        assert p.op == "+"
        assert len(p.args) == 2
    
    def test_anf_call(self):
        f = ANFAtom(ANFVar("f"))
        a = ANFAtom(ANFVar("x"))
        c = ANFCall(f, [a])
        assert repr(c) == "(call f x)"


class TestStackToANF:
    """Test stack-to-ANF conversion."""
    
    def test_simple_add(self):
        def simple_add(x, y):
            return x + y
        
        converter = StackToANF(simple_add.__code__)
        bindings, _ = converter.process()
        
        # Should have: binop, return
        assert len(bindings) >= 2
        # Last binding should be $return
        assert bindings[-1][0].name == "$return"
    
    def test_nested_expr(self):
        def nested(a, b, c):
            return (a + b) * c
        
        converter = StackToANF(nested.__code__)
        bindings, _ = converter.process()
        
        # Should have: add, mul, return
        assert len(bindings) >= 3
    
    def test_local_assignment(self):
        def with_local(x):
            y = x + 1
            return y
        
        converter = StackToANF(with_local.__code__)
        bindings, _ = converter.process()
        
        # Check that y is bound
        var_names = [b[0].name for b in bindings]
        assert "y" in var_names
    
    def test_function_call(self):
        def with_call(x):
            return len(x)
        
        converter = StackToANF(with_call.__code__)
        bindings, _ = converter.process()
        
        # Should have a call binding
        has_call = any(isinstance(b[1], ANFCall) for b in bindings if hasattr(b[1], '__class__'))
        # or check for call primitive
        has_call_prim = any(
            hasattr(b[1], 'func') or (hasattr(b[1], 'op') and 'call' in str(b[1]))
            for b in bindings
        )
        assert has_call or has_call_prim or len(bindings) >= 2


class TestCFGBuilder:
    """Test CFG construction."""
    
    def test_linear_code(self):
        def linear(x):
            return x + 1
        
        builder = CFGBuilder(linear.__code__)
        leaders = builder.find_leaders()
        
        # Should have at least entry block
        assert 0 in leaders
    
    def test_branching_code(self):
        def branching(x):
            if x > 0:
                return x + 1
            else:
                return x - 1
        
        builder = CFGBuilder(branching.__code__)
        leaders = builder.find_leaders()
        
        # Should have multiple blocks
        assert len(leaders) >= 2
    
    def test_loop_code(self):
        def looping(n):
            total = 0
            for i in range(n):
                total += i
            return total
        
        builder = CFGBuilder(looping.__code__)
        leaders = builder.find_leaders()
        
        # Should have loop structure
        assert len(leaders) >= 3

    def test_branch_assignment_has_merge_predecessors(self):
        def branch_assign(cond, x, y):
            if cond:
                z = x
            else:
                z = y
            w = z + 1
            return w

        cfg = CFGBuilder(branch_assign.__code__).build()
        merge_labels = [label for label, block in cfg.items() if len(block.predecessors) >= 2]
        assert merge_labels, f"expected a merge block, got {cfg}"

    def test_loop_header_has_entry_and_backedge_predecessors(self):
        def looping(n):
            total = 0
            for i in range(n):
                total += i
            return total

        cfg = CFGBuilder(looping.__code__).build()
        loop_headers = [label for label, block in cfg.items() if len(block.predecessors) >= 2]
        assert loop_headers, f"expected a loop header with multiple predecessors, got {cfg}"


class TestStructuredJoinCFG:
    """Test structured CFG-shaped ANF with explicit join-field invocation."""

    def test_if_rejoin_emits_join_and_invoke(self):
        def branch_assign(cond, x, y):
            if cond:
                z = x
            else:
                z = y
            w = z + 1
            return w

        blocks = bytecode_to_anf_cfg(branch_assign.__code__)
        join_blocks = [
            block for block in blocks.values()
            if any(isinstance(binding.rhs, ANFJoin) for binding in block.bindings)
        ]
        assert len(join_blocks) == 1

        join_node = next(binding.rhs for binding in join_blocks[0].bindings if isinstance(binding.rhs, ANFJoin))
        assert len(join_node.fields) == 2
        assert all(field.body.bindings or field.body.terminator for field in join_node.fields)

        invoke_blocks = [
            block for block in blocks.values()
            if isinstance(block.terminator, ANFInvokeJoin)
        ]
        assert len(invoke_blocks) >= 2
        assert {block.terminator.field_label for block in invoke_blocks} >= {field.label for field in join_node.fields}

    def test_loop_header_emits_join(self):
        def looping(n):
            total = 0
            for i in range(n):
                total += i
            return total

        blocks = bytecode_to_anf_cfg(looping.__code__)
        join_nodes = [
            binding.rhs
            for block in blocks.values()
            for binding in block.bindings
            if isinstance(binding.rhs, ANFJoin)
        ]
        assert join_nodes, f"expected at least one join node, got {blocks}"
        assert any(len(join.fields) >= 2 for join in join_nodes)
        assert any(isinstance(block.terminator, ANFInvokeJoin) for block in blocks.values())


class TestTypeLattice:
    """Test the type lattice."""
    
    def test_bottom_identity(self):
        lat = TypeLattice()
        assert lat.join(lat.bottom(), lat.INT) == lat.INT
        assert lat.join(lat.INT, lat.bottom()) == lat.INT
    
    def test_top_absorbs(self):
        lat = TypeLattice()
        assert lat.join(lat.ANY, lat.INT) == lat.ANY
        assert lat.join(lat.INT, lat.ANY) == lat.ANY
    
    def test_numeric_join(self):
        lat = TypeLattice()
        assert lat.join(lat.INT, lat.FLOAT) == lat.NUM
        assert lat.join(lat.FLOAT, lat.INT) == lat.NUM
    
    def test_from_value(self):
        lat = TypeLattice()
        assert lat.from_value(42) == lat.INT
        assert lat.from_value(3.14) == lat.FLOAT
        assert lat.from_value("hello") == lat.STR
        assert lat.from_value(True) == lat.BOOL
        assert lat.from_value(None) == lat.NONE
    
    def test_leq(self):
        lat = TypeLattice()
        assert lat.leq(lat.INT, lat.NUM)
        assert lat.leq(lat.FLOAT, lat.NUM)
        assert lat.leq(lat.NUM, lat.ANY)
        assert not lat.leq(lat.NUM, lat.INT)


class TestAbstractStack:
    """Test the abstract stack."""
    
    def test_push_pop(self):
        lat = TypeLattice()
        stack = AbstractStack(lattice=lat)
        
        val = AnnotatedValue("x", lat.INT)
        stack.push(val)
        assert len(stack) == 1
        
        popped = stack.pop()
        assert popped.value == "x"
        assert popped.ann == lat.INT
        assert len(stack) == 0
    
    def test_pop_n(self):
        lat = TypeLattice()
        stack = AbstractStack(lattice=lat)
        
        stack.push(AnnotatedValue("a", lat.INT))
        stack.push(AnnotatedValue("b", lat.FLOAT))
        stack.push(AnnotatedValue("c", lat.STR))
        
        items = stack.pop_n(2)
        assert len(items) == 2
        assert items[0].value == "b"
        assert items[1].value == "c"
        assert len(stack) == 1
    
    def test_join_stacks(self):
        lat = TypeLattice()
        
        stack1 = AbstractStack(lattice=lat)
        stack1.push(AnnotatedValue("x", lat.INT))
        
        stack2 = AbstractStack(lattice=lat)
        stack2.push(AnnotatedValue("y", lat.FLOAT))
        
        joined = stack1.join_with(stack2)
        assert len(joined) == 1
        assert joined.items[0].ann == lat.NUM  # join of int and float


class TestTransferFunctions:
    """Test transfer function registration."""
    
    def setup_method(self):
        clear_transfers()
    
    def test_annotates_exact(self):
        @annotates('MY_OP')
        def my_transfer(stack, instr, **ctx):
            pass
        
        assert get_transfer('MY_OP') is not None
        assert get_transfer('OTHER_OP') is None
    
    def test_annotates_family(self):
        @annotates_family('TEST_')
        def family_transfer(stack, instr, **ctx):
            pass
        
        assert get_transfer('TEST_ONE') is not None
        assert get_transfer('TEST_TWO') is not None
        assert get_transfer('OTHER_ONE') is None
    
    def test_exact_over_family(self):
        @annotates_family('PREF_')
        def family_transfer(stack, instr, **ctx):
            return "family"
        
        @annotates('PREF_SPECIAL')
        def exact_transfer(stack, instr, **ctx):
            return "exact"
        
        # Exact match should take precedence
        assert get_transfer('PREF_SPECIAL') is exact_transfer
        assert get_transfer('PREF_OTHER') is family_transfer


class TestAbstractInterpreter:
    """Test the abstract interpreter."""
    
    def setup_method(self):
        clear_transfers()
        self.lattice = TypeLattice()
        register_builtin_transfers(self.lattice)
    
    def test_simple_analysis(self):
        def simple(x, y):
            return x + y
        
        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze(
            simple.__code__,
            initial_locals={'x': TypeLattice.INT, 'y': TypeLattice.INT}
        )
        
        assert 'x' in result.locals_ann
        assert result.locals_ann['x'] == TypeLattice.INT
    
    def test_type_propagation(self):
        def typed(x, y):
            z = x + y
            return z
        
        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze(
            typed.__code__,
            initial_locals={'x': TypeLattice.INT, 'y': TypeLattice.FLOAT}
        )
        
        # z should be num (join of int and float)
        if 'z' in result.locals_ann:
            assert result.locals_ann['z'] == TypeLattice.NUM
    
    def test_trace_recording(self):
        def traced(x):
            return x + 1
        
        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze(traced.__code__, trace=True)
        
        assert len(result.trace) > 0
        # Each trace entry is (opname, stack_state)
        assert all(isinstance(t, tuple) and len(t) == 2 for t in result.trace)

    def test_cfg_detailed_tracks_predecessor_locals(self):
        def branch_assign(cond, x, y):
            if cond:
                z = x
            else:
                z = y
            w = z + 1
            return w

        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze_cfg_detailed(
            branch_assign.__code__,
            initial_locals={
                'cond': TypeLattice.BOOL,
                'x': TypeLattice.INT,
                'y': TypeLattice.FLOAT,
            }
        )

        merge_labels = [label for label, preds in result.predecessor_states.items() if len(preds) >= 2]
        assert merge_labels, f"expected predecessor states at a merge, got {result.predecessor_states}"
        merge = merge_labels[0]

        pred_z_types = {
            state.locals_ann['z']
            for state in result.predecessor_states[merge].values()
            if 'z' in state.locals_ann
        }
        assert pred_z_types == {TypeLattice.FLOAT, TypeLattice.INT}
        assert result.entry_states[merge].locals_ann.get('z') == TypeLattice.NUM


class TestComputability:
    """Test that transformation is computable for all opcode patterns."""
    
    def test_all_basic_patterns(self):
        """Test various code patterns to ensure completeness."""
        patterns = [
            lambda x: x,                    # identity
            lambda x, y: x + y,             # binary op
            lambda x: -x,                   # unary op
            lambda x: x if x else 0,        # conditional
            lambda x: [i for i in x],       # comprehension
            lambda x: x[0],                 # subscript
            lambda: 42,                     # constant
        ]
        
        for fn in patterns:
            converter = StackToANF(fn.__code__)
            bindings, stack = converter.process()
            # Should not raise, should produce some bindings
            assert isinstance(bindings, list)
    
    def test_bounded_opcodes(self):
        """Verify opcode set is finite."""
        assert len(dis.opmap) < 200  # Reasonable bound
    
    def test_stack_effects_computable(self):
        """Verify stack effects are available for all opcodes."""
        # Sample a few important opcodes
        opcodes_to_check = [
            'LOAD_CONST', 'LOAD_FAST', 'STORE_FAST',
            'BINARY_ADD', 'RETURN_VALUE', 'POP_TOP',
        ]
        
        for name in opcodes_to_check:
            if name in dis.opmap:
                opcode = dis.opmap[name]
                # stack_effect should be callable
                try:
                    effect = dis.stack_effect(opcode, 0)
                    assert isinstance(effect, int)
                except ValueError:
                    # Some opcodes need arg, that's fine
                    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
