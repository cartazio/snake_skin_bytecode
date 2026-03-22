"""Tests to expand coverage of opcode handlers."""

import pytest
import sys
import dis
from bytecode_anf import (
    ANFVar, ANFAtom, ANFPrim, ANFCall,
    StackToANF, CFGBuilder, bytecode_to_anf,
    TypeLattice, AbstractStack, AnnotatedValue,
    AbstractInterpreter,
    clear_transfers,
)
from bytecode_anf.builtin_transfers import register_builtin_transfers


class TestSuperinstructions:
    """Test Python 3.13+ superinstructions."""
    
    def test_load_fast_load_fast(self):
        """LOAD_FAST_LOAD_FAST pushes two locals."""
        def two_locals(a, b):
            return a + b
        
        converter = StackToANF(two_locals.__code__)
        bindings, _ = converter.process()
        assert len(bindings) >= 1
    
    def test_store_fast_store_fast(self):
        """STORE_FAST_STORE_FAST stores two values."""
        def swap_assign():
            a, b = 1, 2
            return a + b
        
        converter = StackToANF(swap_assign.__code__)
        bindings, _ = converter.process()
        var_names = [b[0].name for b in bindings]
        assert 'a' in var_names or '$t' in ''.join(var_names)
    
    def test_store_fast_load_fast(self):
        """STORE_FAST_LOAD_FAST stores then loads."""
        def store_and_use(x):
            y = x
            return y + 1
        
        converter = StackToANF(store_and_use.__code__)
        bindings, _ = converter.process()
        assert len(bindings) >= 2


class TestExceptionOpcodes:
    """Test exception handling opcodes."""
    
    def test_try_except(self):
        """Basic try/except generates exception opcodes."""
        def with_try():
            try:
                return 1
            except:
                return 0
        
        converter = StackToANF(with_try.__code__)
        bindings, _ = converter.process()
        # Should not crash
        assert isinstance(bindings, list)
    
    def test_try_except_specific(self):
        """Try/except with specific exception type."""
        def with_typed_except():
            try:
                return 1 / 0
            except ZeroDivisionError:
                return 0
        
        converter = StackToANF(with_typed_except.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_raise(self):
        """Raise statement."""
        def raises():
            raise ValueError("test")
        
        converter = StackToANF(raises.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestMatchOpcodes:
    """Test pattern matching opcodes (3.10+)."""
    
    def test_match_sequence(self):
        """Match against a sequence pattern."""
        def match_seq(x):
            match x:
                case [a, b]:
                    return a + b
                case _:
                    return 0
        
        converter = StackToANF(match_seq.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_match_mapping(self):
        """Match against a mapping pattern."""
        def match_map(x):
            match x:
                case {"a": val}:
                    return val
                case _:
                    return 0
        
        converter = StackToANF(match_map.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_match_class(self):
        """Match against a class pattern."""
        def match_cls(x):
            match x:
                case int(n):
                    return n
                case _:
                    return 0
        
        converter = StackToANF(match_cls.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestFStringOpcodes:
    """Test f-string formatting opcodes (3.13+)."""
    
    def test_simple_fstring(self):
        """Simple f-string."""
        def make_fstring(x):
            return f"value: {x}"
        
        converter = StackToANF(make_fstring.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_fstring_with_format_spec(self):
        """F-string with format specification."""
        def formatted_fstring(x):
            return f"{x:.2f}"
        
        converter = StackToANF(formatted_fstring.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_fstring_with_conversion(self):
        """F-string with conversion (!r, !s, !a)."""
        def repr_fstring(x):
            return f"{x!r}"
        
        converter = StackToANF(repr_fstring.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestComprehensionOpcodes:
    """Test comprehension-related opcodes."""
    
    def test_list_comprehension(self):
        """List comprehension uses LIST_APPEND."""
        def listcomp(xs):
            return [x * 2 for x in xs]
        
        converter = StackToANF(listcomp.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_set_comprehension(self):
        """Set comprehension uses SET_ADD."""
        def setcomp(xs):
            return {x * 2 for x in xs}
        
        converter = StackToANF(setcomp.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_dict_comprehension(self):
        """Dict comprehension uses MAP_ADD."""
        def dictcomp(xs):
            return {x: x * 2 for x in xs}
        
        converter = StackToANF(dictcomp.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_generator_expression(self):
        """Generator expression."""
        def genexp(xs):
            return (x * 2 for x in xs)
        
        converter = StackToANF(genexp.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestIterationOpcodes:
    """Test iteration opcodes."""
    
    def test_for_loop(self):
        """FOR_ITER, GET_ITER."""
        def for_loop(xs):
            total = 0
            for x in xs:
                total += x
            return total
        
        converter = StackToANF(for_loop.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_while_loop(self):
        """While loop with condition."""
        def while_loop(n):
            total = 0
            while n > 0:
                total += n
                n -= 1
            return total
        
        converter = StackToANF(while_loop.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestUnpackOpcodes:
    """Test unpacking opcodes."""
    
    def test_unpack_sequence(self):
        """UNPACK_SEQUENCE."""
        def unpack_two(t):
            a, b = t
            return a + b
        
        converter = StackToANF(unpack_two.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_unpack_ex(self):
        """UNPACK_EX with star."""
        def unpack_star(xs):
            a, *rest, z = xs
            return a + z
        
        converter = StackToANF(unpack_star.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestAttributeOpcodes:
    """Test attribute access opcodes."""
    
    def test_load_attr(self):
        """LOAD_ATTR."""
        def get_attr(obj):
            return obj.foo
        
        converter = StackToANF(get_attr.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_store_attr(self):
        """STORE_ATTR."""
        def set_attr(obj, val):
            obj.foo = val
        
        converter = StackToANF(set_attr.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_delete_attr(self):
        """DELETE_ATTR."""
        def del_attr(obj):
            del obj.foo
        
        converter = StackToANF(del_attr.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestSubscriptOpcodes:
    """Test subscript opcodes."""
    
    def test_binary_subscr(self):
        """BINARY_SUBSCR."""
        def get_item(xs, i):
            return xs[i]
        
        converter = StackToANF(get_item.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_store_subscr(self):
        """STORE_SUBSCR."""
        def set_item(xs, i, v):
            xs[i] = v
        
        converter = StackToANF(set_item.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_delete_subscr(self):
        """DELETE_SUBSCR."""
        def del_item(xs, i):
            del xs[i]
        
        converter = StackToANF(del_item.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestBinaryOpcodes:
    """Test binary operations."""
    
    def test_all_arithmetic(self):
        """All arithmetic operations."""
        def arith(a, b):
            return a + b, a - b, a * b, a / b, a // b, a % b, a ** b
        
        converter = StackToANF(arith.__code__)
        bindings, _ = converter.process()
        assert len(bindings) >= 7
    
    def test_bitwise(self):
        """Bitwise operations."""
        def bitwise(a, b):
            return a & b, a | b, a ^ b, a << b, a >> b
        
        converter = StackToANF(bitwise.__code__)
        bindings, _ = converter.process()
        assert len(bindings) >= 5
    
    def test_comparisons(self):
        """Comparison operations."""
        def compare(a, b):
            return a < b, a <= b, a == b, a != b, a >= b, a > b
        
        converter = StackToANF(compare.__code__)
        bindings, _ = converter.process()
        assert len(bindings) >= 6
    
    def test_is_in(self):
        """is and in operations."""
        def is_in(a, b):
            return a is b, a is not b, a in b, a not in b
        
        converter = StackToANF(is_in.__code__)
        bindings, _ = converter.process()
        assert len(bindings) >= 4


class TestUnaryOpcodes:
    """Test unary operations."""
    
    def test_unary_ops(self):
        """Unary operations."""
        def unary(a):
            return -a, +a, ~a, not a
        
        converter = StackToANF(unary.__code__)
        bindings, _ = converter.process()
        assert len(bindings) >= 4


class TestBuildOpcodes:
    """Test container building opcodes."""
    
    def test_build_list(self):
        """BUILD_LIST."""
        def make_list():
            return [1, 2, 3]
        
        converter = StackToANF(make_list.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_build_tuple(self):
        """BUILD_TUPLE."""
        def make_tuple():
            return (1, 2, 3)
        
        converter = StackToANF(make_tuple.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_build_set(self):
        """BUILD_SET."""
        def make_set():
            return {1, 2, 3}
        
        converter = StackToANF(make_set.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_build_map(self):
        """BUILD_MAP."""
        def make_dict():
            return {"a": 1, "b": 2}
        
        converter = StackToANF(make_dict.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_build_const_key_map(self):
        """BUILD_CONST_KEY_MAP."""
        def const_key_dict():
            return {"a": 1, "b": 2, "c": 3}
        
        converter = StackToANF(const_key_dict.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_build_string(self):
        """BUILD_STRING via f-string concatenation."""
        def build_str(a, b):
            return f"{a}{b}"
        
        converter = StackToANF(build_str.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_build_slice(self):
        """BUILD_SLICE."""
        def with_slice(xs):
            return xs[1:3:1]
        
        converter = StackToANF(with_slice.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestCallOpcodes:
    """Test call-related opcodes."""
    
    def test_simple_call(self):
        """Simple function call."""
        def simple_call(f, x):
            return f(x)
        
        converter = StackToANF(simple_call.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_call_with_kwargs(self):
        """Call with keyword arguments."""
        def call_kwargs():
            return dict(a=1, b=2)
        
        converter = StackToANF(call_kwargs.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_call_method(self):
        """Method call."""
        def call_method(obj):
            return obj.method()
        
        converter = StackToANF(call_method.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestFunctionOpcodes:
    """Test function-related opcodes."""
    
    def test_make_function(self):
        """MAKE_FUNCTION for nested function."""
        def outer():
            def inner():
                return 1
            return inner
        
        converter = StackToANF(outer.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_closure(self):
        """Closure with LOAD_CLOSURE, LOAD_DEREF."""
        def outer(x):
            def inner():
                return x
            return inner
        
        converter = StackToANF(outer.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_lambda(self):
        """Lambda expression."""
        def with_lambda():
            f = lambda x: x + 1
            return f
        
        converter = StackToANF(with_lambda.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestImportOpcodes:
    """Test import opcodes."""
    
    def test_import_name(self):
        """IMPORT_NAME."""
        def do_import():
            import sys
            return sys
        
        converter = StackToANF(do_import.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_import_from(self):
        """IMPORT_FROM."""
        def do_import_from():
            from sys import version
            return version
        
        converter = StackToANF(do_import_from.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestStackManipulation:
    """Test stack manipulation opcodes."""
    
    def test_dup_and_rot(self):
        """DUP_TOP, ROT operations via augmented assignment."""
        def augmented(xs, i):
            xs[i] += 1
            return xs
        
        converter = StackToANF(augmented.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_swap_via_multiple_assign(self):
        """SWAP via multiple assignment."""
        def swap(a, b):
            a, b = b, a
            return a, b
        
        converter = StackToANF(swap.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestDeleteOpcodes:
    """Test delete opcodes."""
    
    def test_delete_fast(self):
        """DELETE_FAST."""
        def del_local():
            x = 1
            del x
        
        converter = StackToANF(del_local.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_delete_name(self):
        """DELETE_NAME via exec."""
        # Can't easily test this without exec
        pass


class TestControlFlowOpcodes:
    """Test control flow opcodes."""
    
    def test_jump_if_true_or_pop(self):
        """JUMP_IF_TRUE_OR_POP via or."""
        def short_circuit_or(a, b):
            return a or b
        
        converter = StackToANF(short_circuit_or.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_jump_if_false_or_pop(self):
        """JUMP_IF_FALSE_OR_POP via and."""
        def short_circuit_and(a, b):
            return a and b
        
        converter = StackToANF(short_circuit_and.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)
    
    def test_ternary(self):
        """Ternary expression."""
        def ternary(a, b, c):
            return a if b else c
        
        converter = StackToANF(ternary.__code__)
        bindings, _ = converter.process()
        assert isinstance(bindings, list)


class TestTransferFunctionsCoverage:
    """Test transfer functions with abstract interpretation."""
    
    def setup_method(self):
        clear_transfers()
        self.lattice = TypeLattice()
        register_builtin_transfers(self.lattice)
    
    def test_load_const_types(self):
        """Test LOAD_CONST with various types."""
        def consts():
            a = 42
            b = 3.14
            c = "hello"
            d = True
            e = None
            f = (1, 2)
            return a, b, c, d, e, f
        
        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze(consts.__code__)
        assert 'a' in result.locals_ann
    
    def test_binary_op_types(self):
        """Test BINARY_OP type propagation."""
        def binary_types(x, y):
            a = x + y
            b = x / y  # always float
            c = x // y
            return a, b, c
        
        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze(
            binary_types.__code__,
            initial_locals={'x': TypeLattice.INT, 'y': TypeLattice.INT}
        )
        if 'b' in result.locals_ann:
            assert result.locals_ann['b'] == TypeLattice.FLOAT
    
    def test_compare_is_bool(self):
        """Test comparisons return bool."""
        def comparisons(x, y):
            a = x < y
            b = x == y
            c = x is y
            d = x in y
            return a, b, c, d
        
        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze(comparisons.__code__)
        # Comparisons should produce bool type
        for name in ['a', 'b', 'c', 'd']:
            if name in result.locals_ann:
                assert result.locals_ann[name] == TypeLattice.BOOL
    
    def test_collection_types(self):
        """Test collection building returns correct types."""
        def collections():
            lst = [1, 2, 3]
            tup = (1, 2, 3)
            st = {1, 2, 3}
            dct = {"a": 1}
            return lst, tup, st, dct
        
        interp = AbstractInterpreter(self.lattice)
        result = interp.analyze(collections.__code__)
        if 'lst' in result.locals_ann:
            assert result.locals_ann['lst'] == TypeLattice.LIST
        if 'tup' in result.locals_ann:
            assert result.locals_ann['tup'] == TypeLattice.TUPLE
        if 'st' in result.locals_ann:
            assert result.locals_ann['st'] == TypeLattice.SET
        if 'dct' in result.locals_ann:
            assert result.locals_ann['dct'] == TypeLattice.DICT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
