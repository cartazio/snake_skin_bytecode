"""
Built-in transfer functions for common opcodes.

These implement type propagation for the TypeLattice.
Users can register their own transfer functions for
custom lattices or more precise semantics.
"""

from __future__ import annotations
from typing import Dict, Any, Optional

from .lattice import AbstractStack, AnnotatedValue
from .transfer import annotates, annotates_family, get_default_registry, TransferRegistry
from .builtin_lattices import TypeLattice, SimpleType


def register_builtin_transfers(
    lattice: TypeLattice,
    registry: Optional[TransferRegistry] = None
) -> None:
    """
    Register built-in transfer functions.
    
    Args:
        lattice: The type lattice to use for value annotations
        registry: Optional registry to register to (default: global registry)
    
    Call this once with your lattice instance to enable
    default type propagation. Pass a custom registry to avoid
    polluting the global registry.
    """
    if registry is None:
        registry = get_default_registry()
    
    # Transfer functions close over the lattice
    _register_loads(lattice, registry)
    _register_stores(lattice, registry)
    _register_binary(lattice, registry)
    _register_unary(lattice, registry)
    _register_calls(lattice, registry)
    _register_control(lattice, registry)
    _register_build(lattice, registry)
    _register_3_12_plus(lattice, registry)
    _register_3_13_plus(lattice, registry)
    _register_3_14_plus(lattice, registry)


def _register_loads(lattice: TypeLattice, registry: TransferRegistry):
    """Register LOAD_* transfer functions."""
    
    @registry.annotates('LOAD_CONST')
    def xfer_load_const(stack: AbstractStack, instr, **ctx):
        val = instr.argval
        ann = lattice.from_value(val)
        stack.push(AnnotatedValue(repr(val), ann))
    
    @registry.annotates('LOAD_FAST', 'LOAD_FAST_CHECK', 'LOAD_FAST_BORROW')
    def xfer_load_fast(stack: AbstractStack, instr, locals_ann: Dict[str, SimpleType], **ctx):
        name = instr.argval
        ann = locals_ann.get(name, lattice.ANY)
        stack.push(AnnotatedValue(name, ann))
    
    @registry.annotates('LOAD_GLOBAL')
    def xfer_load_global(stack: AbstractStack, instr, **ctx):
        # Globals are generally unknown
        stack.push(AnnotatedValue(f"global:{instr.argval}", lattice.ANY))
    
    @registry.annotates('LOAD_ATTR')
    def xfer_load_attr(stack: AbstractStack, instr, **ctx):
        obj = stack.pop()
        # Attribute types are generally unknown without more info
        stack.push(AnnotatedValue(f"{obj.value}.{instr.argval}", lattice.ANY))
    
    @registry.annotates('LOAD_NAME')
    def xfer_load_name(stack: AbstractStack, instr, **ctx):
        stack.push(AnnotatedValue(f"name:{instr.argval}", lattice.ANY))
    
    @registry.annotates('LOAD_DEREF')
    def xfer_load_deref(stack: AbstractStack, instr, **ctx):
        stack.push(AnnotatedValue(f"deref:{instr.argval}", lattice.ANY))
    
    @registry.annotates('LOAD_METHOD')
    def xfer_load_method(stack: AbstractStack, instr, **ctx):
        obj = stack.pop()
        stack.push(AnnotatedValue(None, lattice.NONE))  # NULL placeholder
        stack.push(AnnotatedValue(f"{obj.value}.{instr.argval}", lattice.CALLABLE))


def _register_stores(lattice: TypeLattice, registry: TransferRegistry):
    """Register STORE_* transfer functions."""
    
    @registry.annotates('STORE_FAST')
    def xfer_store_fast(stack: AbstractStack, instr, locals_ann: Dict[str, SimpleType], **ctx):
        val = stack.pop()
        locals_ann[instr.argval] = val.ann
    
    @registry.annotates('STORE_NAME')
    def xfer_store_name(stack: AbstractStack, instr, **ctx):
        stack.pop()  # Value is stored, not used further
    
    @registry.annotates('STORE_GLOBAL')
    def xfer_store_global(stack: AbstractStack, instr, **ctx):
        stack.pop()
    
    @registry.annotates('STORE_ATTR')
    def xfer_store_attr(stack: AbstractStack, instr, **ctx):
        stack.pop()  # value
        stack.pop()  # object
    
    @registry.annotates('STORE_SUBSCR')
    def xfer_store_subscr(stack: AbstractStack, instr, **ctx):
        stack.pop()  # value
        stack.pop()  # key
        stack.pop()  # object


def _register_binary(lattice: TypeLattice, registry: TransferRegistry):
    """Register binary operation transfer functions."""
    
    @registry.annotates('BINARY_OP')
    def xfer_binary_op(stack: AbstractStack, instr, **ctx):
        b = stack.pop()
        a = stack.pop()
        
        # Operation code determines result type behavior
        op_code = instr.arg
        
        # Division always returns float
        if op_code in (2, 11, 15, 24):  # //, /, //=, /=
            if op_code == 11 or op_code == 24:  # true division
                result_ann = lattice.FLOAT
            else:
                result_ann = lattice.join(a.ann, b.ann)
        else:
            result_ann = lattice.join(a.ann, b.ann)
        
        stack.push(AnnotatedValue(f"({a.value} op {b.value})", result_ann))
    
    @registry.annotates_family('BINARY_')
    def xfer_binary_family(stack: AbstractStack, instr, **ctx):
        b = stack.pop()
        a = stack.pop()
        op = instr.opname
        
        if 'TRUE_DIVIDE' in op:
            result_ann = lattice.FLOAT
        elif 'SUBSCR' in op:
            result_ann = lattice.ANY  # Element type unknown
        else:
            result_ann = lattice.join(a.ann, b.ann)
        
        stack.push(AnnotatedValue(f"({a.value} {op} {b.value})", result_ann))
    
    @registry.annotates('COMPARE_OP', 'IS_OP', 'CONTAINS_OP')
    def xfer_compare(stack: AbstractStack, instr, **ctx):
        stack.pop()
        stack.pop()
        stack.push(AnnotatedValue("cmp_result", lattice.BOOL))


def _register_unary(lattice: TypeLattice, registry: TransferRegistry):
    """Register unary operation transfer functions."""
    
    @registry.annotates_family('UNARY_')
    def xfer_unary(stack: AbstractStack, instr, **ctx):
        a = stack.pop()
        op = instr.opname
        
        if 'NOT' in op:
            result_ann = lattice.BOOL
        else:
            result_ann = a.ann
        
        stack.push(AnnotatedValue(f"({op} {a.value})", result_ann))


def _register_calls(lattice: TypeLattice, registry: TransferRegistry):
    """Register call-related transfer functions."""
    
    @registry.annotates('CALL', 'CALL_FUNCTION', 'CALL_METHOD')
    def xfer_call(stack: AbstractStack, instr, **ctx):
        argc = instr.arg or 0
        
        # Pop arguments
        for _ in range(argc):
            stack.pop()
        
        # Pop function/method
        func = stack.pop()
        
        # For CALL in Python 3.11+, also pop NULL
        if instr.opname == 'CALL' and stack.items and stack.items[-1].value is None:
            stack.pop()
        
        # For CALL_METHOD, pop self/NULL
        if instr.opname == 'CALL_METHOD':
            stack.pop()
        
        # Return type is generally unknown
        # Could be refined with known function signatures
        stack.push(AnnotatedValue(f"call({func.value})", lattice.ANY))
    
    @registry.annotates('CALL_FUNCTION_KW')
    def xfer_call_kw(stack: AbstractStack, instr, **ctx):
        stack.pop()  # kw names tuple
        argc = instr.arg
        for _ in range(argc):
            stack.pop()
        func = stack.pop()
        stack.push(AnnotatedValue(f"call({func.value})", lattice.ANY))


def _register_control(lattice: TypeLattice, registry: TransferRegistry):
    """Register control flow transfer functions."""
    
    @registry.annotates('RETURN_VALUE')
    def xfer_return(stack: AbstractStack, instr, **ctx):
        val = stack.pop()
        return ('return', val.value, val.ann)
    
    @registry.annotates('RETURN_CONST')
    def xfer_return_const(stack: AbstractStack, instr, **ctx):
        ann = lattice.from_value(instr.argval)
        return ('return', instr.argval, ann)
    
    @registry.annotates('POP_JUMP_IF_TRUE', 'POP_JUMP_IF_FALSE',
               'POP_JUMP_IF_NONE', 'POP_JUMP_IF_NOT_NONE')
    def xfer_pop_jump(stack: AbstractStack, instr, **ctx):
        stack.pop()
    
    @registry.annotates('JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP_ABSOLUTE',
               'JUMP_BACKWARD_NO_INTERRUPT', 'JUMP_IF_TRUE_OR_POP',
               'JUMP_IF_FALSE_OR_POP')
    def xfer_jump(stack: AbstractStack, instr, **ctx):
        pass  # No stack effect for unconditional jumps


def _register_build(lattice: TypeLattice, registry: TransferRegistry):
    """Register structure building transfer functions."""
    
    @registry.annotates('BUILD_LIST', 'LIST_EXTEND')
    def xfer_build_list(stack: AbstractStack, instr, **ctx):
        n = instr.arg or 0
        for _ in range(n):
            stack.pop()
        stack.push(AnnotatedValue("list", lattice.LIST))
    
    @registry.annotates('BUILD_TUPLE')
    def xfer_build_tuple(stack: AbstractStack, instr, **ctx):
        n = instr.arg or 0
        for _ in range(n):
            stack.pop()
        stack.push(AnnotatedValue("tuple", lattice.TUPLE))
    
    @registry.annotates('BUILD_SET', 'SET_UPDATE')
    def xfer_build_set(stack: AbstractStack, instr, **ctx):
        n = instr.arg or 0
        for _ in range(n):
            stack.pop()
        stack.push(AnnotatedValue("set", lattice.SET))
    
    @registry.annotates('BUILD_MAP', 'BUILD_CONST_KEY_MAP', 'DICT_UPDATE')
    def xfer_build_dict(stack: AbstractStack, instr, **ctx):
        op = instr.opname
        if op == 'BUILD_MAP':
            n = (instr.arg or 0) * 2
        elif op == 'BUILD_CONST_KEY_MAP':
            n = (instr.arg or 0) + 1  # values + keys tuple
        else:
            n = 1
        for _ in range(n):
            stack.pop()
        stack.push(AnnotatedValue("dict", lattice.DICT))
    
    @registry.annotates('BUILD_STRING')
    def xfer_build_string(stack: AbstractStack, instr, **ctx):
        n = instr.arg or 0
        for _ in range(n):
            stack.pop()
        stack.push(AnnotatedValue("str", lattice.STR))
    
    @registry.annotates('BUILD_SLICE')
    def xfer_build_slice(stack: AbstractStack, instr, **ctx):
        n = instr.arg or 2
        for _ in range(n):
            stack.pop()
        stack.push(AnnotatedValue("slice", lattice.ANY))
    
    @registry.annotates('GET_ITER')
    def xfer_get_iter(stack: AbstractStack, instr, **ctx):
        stack.pop()
        stack.push(AnnotatedValue("iter", lattice.ITERATOR))
    
    @registry.annotates('FOR_ITER')
    def xfer_for_iter(stack: AbstractStack, instr, **ctx):
        # Complex: pops iterator, pushes iterator + next value
        it = stack.pop()
        stack.push(it)  # re-push iterator
        stack.push(AnnotatedValue("next", lattice.ANY))
    
    @registry.annotates('END_FOR')
    def xfer_end_for(stack: AbstractStack, instr, **ctx):
        stack.pop()  # pop iterator
    
    @registry.annotates('UNPACK_SEQUENCE')
    def xfer_unpack(stack: AbstractStack, instr, **ctx):
        stack.pop()
        n = instr.arg or 0
        for i in range(n):
            stack.push(AnnotatedValue(f"unpack[{i}]", lattice.ANY))
    
    # Stack manipulation
    @registry.annotates('POP_TOP')
    def xfer_pop_top(stack: AbstractStack, instr, **ctx):
        stack.pop()
    
    @registry.annotates('DUP_TOP')
    def xfer_dup_top(stack: AbstractStack, instr, **ctx):
        stack.push(stack.items[-1])
    
    @registry.annotates('ROT_TWO')
    def xfer_rot_two(stack: AbstractStack, instr, **ctx):
        a = stack.pop()
        b = stack.pop()
        stack.push(a)
        stack.push(b)
    
    @registry.annotates('ROT_THREE')
    def xfer_rot_three(stack: AbstractStack, instr, **ctx):
        a = stack.pop()
        b = stack.pop()
        c = stack.pop()
        stack.push(a)
        stack.push(c)
        stack.push(b)
    
    @registry.annotates('COPY')
    def xfer_copy(stack: AbstractStack, instr, **ctx):
        n = instr.arg
        if n > 0 and n <= len(stack.items):
            stack.push(stack.items[-n])
    
    @registry.annotates('SWAP')
    def xfer_swap(stack: AbstractStack, instr, **ctx):
        n = instr.arg
        if n > 0 and n <= len(stack.items):
            stack.items[-1], stack.items[-n] = stack.items[-n], stack.items[-1]
    
    # No-ops
    @registry.annotates('RESUME', 'PUSH_NULL', 'PRECALL', 'NOP', 'CACHE')
    def xfer_noop(stack: AbstractStack, instr, **ctx):
        if instr.opname == 'PUSH_NULL':
            stack.push(AnnotatedValue(None, lattice.NONE))
    
    # Functions
    @registry.annotates('MAKE_FUNCTION')
    def xfer_make_function(stack: AbstractStack, instr, **ctx):
        stack.pop()  # code object
        stack.push(AnnotatedValue("function", lattice.CALLABLE))
    
    @registry.annotates('LOAD_CLOSURE')
    def xfer_load_closure(stack: AbstractStack, instr, **ctx):
        stack.push(AnnotatedValue(f"closure:{instr.argval}", lattice.ANY))
    
    @registry.annotates('LOAD_BUILD_CLASS')
    def xfer_load_build_class(stack: AbstractStack, instr, **ctx):
        stack.push(AnnotatedValue("__build_class__", lattice.CALLABLE))


def _register_3_12_plus(lattice: TypeLattice, registry: TransferRegistry):
    """Register transfer functions for Python 3.12+ opcodes."""

    @registry.annotates('LOAD_FAST_AND_CLEAR')
    def xfer_load_fast_and_clear(stack: AbstractStack, instr, locals_ann: Dict[str, SimpleType], **ctx):
        name = instr.argval
        ann = locals_ann.get(name, lattice.ANY)
        stack.push(AnnotatedValue(name, ann))

    @registry.annotates('LOAD_SUPER_ATTR')
    def xfer_load_super_attr(stack: AbstractStack, instr, **ctx):
        stack.pop()  # attr name
        stack.pop()  # class
        stack.pop()  # self
        stack.push(AnnotatedValue(f"super.{instr.argval}", lattice.ANY))

    @registry.annotates('CALL_INTRINSIC_1')
    def xfer_intrinsic_1(stack: AbstractStack, instr, **ctx):
        stack.pop()
        stack.push(AnnotatedValue(f"intrinsic1:{instr.arg}", lattice.ANY))

    @registry.annotates('CALL_INTRINSIC_2')
    def xfer_intrinsic_2(stack: AbstractStack, instr, **ctx):
        stack.pop()
        stack.pop()
        stack.push(AnnotatedValue(f"intrinsic2:{instr.arg}", lattice.ANY))

    @registry.annotates('END_SEND')
    def xfer_end_send(stack: AbstractStack, instr, **ctx):
        stack.pop()  # pop sent value, keep result

    @registry.annotates('RETURN_GENERATOR', 'COPY_FREE_VARS', 'MAKE_CELL')
    def xfer_noop_3_12(stack: AbstractStack, instr, **ctx):
        pass  # No stack effect

    @registry.annotates('MATCH_SEQUENCE', 'MATCH_MAPPING')
    def xfer_match_check(stack: AbstractStack, instr, **ctx):
        stack.pop()
        stack.push(AnnotatedValue("match_result", lattice.BOOL))

    @registry.annotates('MATCH_CLASS')
    def xfer_match_class(stack: AbstractStack, instr, **ctx):
        n = instr.arg or 0
        for _ in range(n):
            stack.pop()
        stack.pop()  # subject
        stack.push(AnnotatedValue("match_class_result", lattice.ANY))

    @registry.annotates('MATCH_KEYS')
    def xfer_match_keys(stack: AbstractStack, instr, **ctx):
        stack.pop()  # keys tuple
        # mapping stays on stack (peek), push result
        stack.push(AnnotatedValue("match_keys_result", lattice.ANY))

    @registry.annotates('PUSH_EXC_INFO')
    def xfer_push_exc_info(stack: AbstractStack, instr, **ctx):
        # Push exception info onto stack
        stack.push(AnnotatedValue("exc_info", lattice.ANY))

    @registry.annotates('POP_EXCEPT')
    def xfer_pop_except(stack: AbstractStack, instr, **ctx):
        if stack.items:
            stack.pop()

    @registry.annotates('CHECK_EXC_MATCH')
    def xfer_check_exc_match(stack: AbstractStack, instr, **ctx):
        stack.pop()  # exception type
        stack.push(AnnotatedValue("exc_match", lattice.BOOL))


def _register_3_13_plus(lattice: TypeLattice, registry: TransferRegistry):
    """Register transfer functions for Python 3.13+ opcodes."""

    @registry.annotates('LOAD_FAST_LOAD_FAST', 'LOAD_FAST_BORROW_LOAD_FAST_BORROW')
    def xfer_load_fast_load_fast(stack: AbstractStack, instr,
                                  locals_ann: Dict[str, SimpleType], **ctx):
        # Superinstruction: pushes two locals
        # argval = (name1, name2); name1 pushed first (deeper), name2 on top
        name1, name2 = instr.argval
        ann1 = locals_ann.get(name1, lattice.ANY)
        ann2 = locals_ann.get(name2, lattice.ANY)
        stack.push(AnnotatedValue(name1, ann1))
        stack.push(AnnotatedValue(name2, ann2))

    @registry.annotates('STORE_FAST_STORE_FAST')
    def xfer_store_fast_store_fast(stack: AbstractStack, instr,
                                    locals_ann: Dict[str, SimpleType], **ctx):
        # Superinstruction: pops TOS → argval[0], TOS-1 → argval[1]
        name1, name2 = instr.argval
        val1 = stack.pop()
        val2 = stack.pop()
        locals_ann[name1] = val1.ann
        locals_ann[name2] = val2.ann

    @registry.annotates('STORE_FAST_LOAD_FAST')
    def xfer_store_fast_load_fast(stack: AbstractStack, instr,
                                   locals_ann: Dict[str, SimpleType], **ctx):
        # Superinstruction: stores TOS → argval[0], loads argval[1]
        name_store, name_load = instr.argval
        val = stack.pop()
        locals_ann[name_store] = val.ann
        ann_load = locals_ann.get(name_load, lattice.ANY)
        stack.push(AnnotatedValue(name_load, ann_load))

    @registry.annotates('TO_BOOL')
    def xfer_to_bool(stack: AbstractStack, instr, **ctx):
        # 3.13: bool(TOS), replaces TOS
        stack.pop()
        stack.push(AnnotatedValue("bool_result", lattice.BOOL))

    @registry.annotates('CALL_KW')
    def xfer_call_kw(stack: AbstractStack, instr, **ctx):
        # 3.13: call with keyword args
        # Stack: callable, self/NULL, args..., kw_names_tuple
        kw_names = stack.pop()
        argc = instr.arg or 0
        for _ in range(argc):
            stack.pop()
        func = stack.pop()
        # Pop NULL if present
        if stack.items and stack.items[-1].value is None:
            stack.pop()
        stack.push(AnnotatedValue(f"call_kw({func.value})", lattice.ANY))

    @registry.annotates('FORMAT_SIMPLE')
    def xfer_format_simple(stack: AbstractStack, instr, **ctx):
        # 3.13: TOS = TOS.__format__("")
        stack.pop()
        stack.push(AnnotatedValue("formatted", lattice.STR))

    @registry.annotates('FORMAT_WITH_SPEC')
    def xfer_format_with_spec(stack: AbstractStack, instr, **ctx):
        # 3.13: spec=pop, val=pop, push val.__format__(spec)
        stack.pop()  # spec
        stack.pop()  # value
        stack.push(AnnotatedValue("formatted", lattice.STR))

    @registry.annotates('CONVERT_VALUE')
    def xfer_convert_value(stack: AbstractStack, instr, **ctx):
        # 3.13: convert for f-string (1=str, 2=repr, 3=ascii)
        stack.pop()
        stack.push(AnnotatedValue("converted", lattice.STR))

    @registry.annotates('SET_FUNCTION_ATTRIBUTE')
    def xfer_set_func_attr(stack: AbstractStack, instr, **ctx):
        # 3.13: pops attr value + func, pushes func with attr set
        stack.pop()  # attr value
        stack.pop()  # func
        stack.push(AnnotatedValue("function", lattice.CALLABLE))

    @registry.annotates('LOAD_LOCALS')
    def xfer_load_locals(stack: AbstractStack, instr, **ctx):
        stack.push(AnnotatedValue("locals", lattice.DICT))

    @registry.annotates('LOAD_FROM_DICT_OR_DEREF', 'LOAD_FROM_DICT_OR_GLOBALS')
    def xfer_load_from_dict(stack: AbstractStack, instr, **ctx):
        # Pops mapping, looks up name, pushes result
        stack.pop()
        stack.push(AnnotatedValue(f"lookup:{instr.argval}", lattice.ANY))

    @registry.annotates('LIST_APPEND')
    def xfer_list_append(stack: AbstractStack, instr, **ctx):
        stack.pop()  # item popped, container stays

    @registry.annotates('SET_ADD')
    def xfer_set_add(stack: AbstractStack, instr, **ctx):
        stack.pop()  # item popped, container stays

    @registry.annotates('MAP_ADD')
    def xfer_map_add(stack: AbstractStack, instr, **ctx):
        stack.pop()  # value
        stack.pop()  # key; container stays

    @registry.annotates('DICT_MERGE')
    def xfer_dict_merge(stack: AbstractStack, instr, **ctx):
        stack.pop()  # mapping to merge

    @registry.annotates('UNPACK_EX')
    def xfer_unpack_ex(stack: AbstractStack, instr, **ctx):
        stack.pop()  # iterable
        before = (instr.arg or 0) & 0xFF
        after = ((instr.arg or 0) >> 8) & 0xFF
        total = before + 1 + after
        for i in range(total):
            stack.push(AnnotatedValue(f"unpack_ex[{i}]", lattice.ANY))

    @registry.annotates('STORE_DEREF')
    def xfer_store_deref(stack: AbstractStack, instr, **ctx):
        stack.pop()

    @registry.annotates('DELETE_FAST', 'DELETE_NAME', 'DELETE_GLOBAL', 'DELETE_DEREF')
    def xfer_delete(stack: AbstractStack, instr, **ctx):
        pass  # No stack effect

    @registry.annotates('DELETE_ATTR')
    def xfer_delete_attr(stack: AbstractStack, instr, **ctx):
        stack.pop()  # object

    @registry.annotates('DELETE_SUBSCR')
    def xfer_delete_subscr(stack: AbstractStack, instr, **ctx):
        stack.pop()  # key
        stack.pop()  # object

    @registry.annotates('NOT_TAKEN')
    def xfer_not_taken(stack: AbstractStack, instr, **ctx):
        pass  # NOP branch hint


def _register_3_14_plus(lattice: TypeLattice, registry: TransferRegistry):
    """Register transfer functions for Python 3.14+ opcodes."""

    @registry.annotates('LOAD_SMALL_INT')
    def xfer_load_small_int(stack: AbstractStack, instr, **ctx):
        # 3.14: pushes small integer (0-255)
        stack.push(AnnotatedValue(repr(instr.argval), lattice.INT))

    @registry.annotates('LOAD_COMMON_CONSTANT')
    def xfer_load_common_constant(stack: AbstractStack, instr, **ctx):
        # 3.14: loads hardcoded constants (e.g. AssertionError)
        stack.push(AnnotatedValue(f"common_const:{instr.arg}", lattice.ANY))

    @registry.annotates('LOAD_SPECIAL')
    def xfer_load_special(stack: AbstractStack, instr, **ctx):
        # 3.14: special method lookup on TOS, pushes method + self/NULL
        obj = stack.pop()
        stack.push(AnnotatedValue(f"special({obj.value})", lattice.CALLABLE))
        stack.push(AnnotatedValue(None, lattice.NONE))  # NULL or self

    @registry.annotates('POP_ITER')
    def xfer_pop_iter(stack: AbstractStack, instr, **ctx):
        # 3.14: pops iterator
        stack.pop()

    @registry.annotates('BUILD_INTERPOLATION')
    def xfer_build_interpolation(stack: AbstractStack, instr, **ctx):
        # 3.14 (PEP 750): builds Interpolation
        has_spec = (instr.arg or 0) & 1
        if has_spec:
            stack.pop()  # format_spec
        stack.pop()  # conversion
        stack.pop()  # expression string
        stack.pop()  # value
        stack.push(AnnotatedValue("interpolation", lattice.ANY))

    @registry.annotates('BUILD_TEMPLATE')
    def xfer_build_template(stack: AbstractStack, instr, **ctx):
        # 3.14 (PEP 750): builds Template from strings + interpolations
        stack.pop()  # interpolations
        stack.pop()  # strings
        stack.push(AnnotatedValue("template", lattice.ANY))
