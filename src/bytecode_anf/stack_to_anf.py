"""
Stack machine to ANF conversion.

Core insight (Danvy): stack machine execution corresponds directly
to CPS/ANF. Stack positions are continuation variables.

- PUSH = let-bind a new value
- POP = use a bound variable
- Stack depth = continuation depth
"""

from __future__ import annotations
import dis
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional, Any, Union
from types import CodeType

from .anf import (
    ANFVar, ANFAtom, ANFPrim, ANFCall, ANFLet,
    ANFBranch, ANFJump, ANFReturn, ANFExpr, ANFTerminator
)


@dataclass
class BasicBlock:
    """
    A basic block in the CFG.
    
    Contains straight-line ANF bindings and a terminator.
    """
    label: int  # Bytecode offset of first instruction
    bindings: List[Tuple[ANFVar, ANFExpr]] = field(default_factory=list)
    terminator: Optional[ANFTerminator] = None
    predecessors: List[int] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)
    
    def add_binding(self, var: ANFVar, rhs: ANFExpr) -> None:
        self.bindings.append((var, rhs))
    
    def __repr__(self) -> str:
        lines = [f"BB{self.label}:"]
        for var, rhs in self.bindings:
            lines.append(f"  let {var} = {rhs}")
        if self.terminator:
            lines.append(f"  {self.terminator}")
        return "\n".join(lines)


class CFGBuilder:
    """
    Build a control flow graph from bytecode.
    
    Identifies basic block boundaries (leaders) and edges.
    """
    
    # Opcodes that end a basic block
    TERMINATORS = frozenset([
        'RETURN_VALUE', 'RETURN_CONST', 'RAISE_VARARGS', 'RERAISE',
    ])
    
    # Opcodes that transfer control (but may fall through)
    JUMPS = frozenset([
        'JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP_ABSOLUTE',
        'JUMP_BACKWARD_NO_INTERRUPT',
        'POP_JUMP_IF_TRUE', 'POP_JUMP_IF_FALSE',
        'POP_JUMP_IF_NONE', 'POP_JUMP_IF_NOT_NONE',
        'JUMP_IF_TRUE_OR_POP', 'JUMP_IF_FALSE_OR_POP',
        'FOR_ITER', 'SEND',
    ])
    
    def __init__(self, code: CodeType):
        self.code = code
        self.instructions = list(dis.Bytecode(code))
        self.offset_to_idx = {instr.offset: i for i, instr in enumerate(self.instructions)}
        self.blocks: Dict[int, BasicBlock] = {}
        self.leaders: Set[int] = set()
    
    def find_leaders(self) -> List[int]:
        """
        Find basic block leaders (first instruction of each block).
        
        Leaders are:
        1. First instruction
        2. Target of any jump
        3. Instruction following a jump or terminator
        """
        self.leaders = {0}  # Entry is always a leader
        
        for i, instr in enumerate(self.instructions):
            op = instr.opname
            
            if op in self.JUMPS or op in self.TERMINATORS:
                # Jump target is a leader
                if instr.argval is not None and isinstance(instr.argval, int):
                    self.leaders.add(instr.argval)
                
                # Fall-through (next instruction) is a leader
                if i + 1 < len(self.instructions):
                    self.leaders.add(self.instructions[i + 1].offset)
        
        return sorted(self.leaders)
    
    def build(self) -> Dict[int, BasicBlock]:
        """Build the CFG and return the blocks."""
        leaders = self.find_leaders()
        
        # Create blocks
        for leader in leaders:
            self.blocks[leader] = BasicBlock(label=leader)
        
        # Assign instructions to blocks and compute edges
        current_label = 0
        
        for instr in self.instructions:
            if instr.offset in self.leaders and instr.offset != 0:
                current_label = instr.offset
            
            block = self.blocks[current_label]
            op = instr.opname
            
            # Compute successor edges
            if op in self.TERMINATORS:
                pass  # No successors
            elif op in self.JUMPS:
                target = instr.argval
                if target is not None and isinstance(target, int):
                    block.successors.append(target)
                    self.blocks[target].predecessors.append(current_label)
                
                # Check for fall-through
                idx = self.offset_to_idx[instr.offset]
                if idx + 1 < len(self.instructions):
                    if op not in ('JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP_ABSOLUTE',
                                  'JUMP_BACKWARD_NO_INTERRUPT'):
                        # Conditional jump: also falls through
                        fall_through = self.instructions[idx + 1].offset
                        if fall_through in self.leaders:
                            block.successors.append(fall_through)
                            self.blocks[fall_through].predecessors.append(current_label)
        
        return self.blocks


class StackToANF:
    """
    Convert bytecode to ANF via stack simulation.
    
    The stack discipline directly corresponds to ANF:
    - Each push creates a let-binding
    - Each pop uses a bound variable
    - Binary ops consume two bindings, produce one
    
    This is Danvy's insight: defunctionalization of the stack
    yields CPS/ANF.
    """
    
    def __init__(self, code: Optional[CodeType] = None):
        self.code = code
        self.counter = 0
        self.bindings: List[Tuple[ANFVar, ANFExpr]] = []
        self.stack: List[ANFAtom] = []
        self.locals_map: Dict[str, ANFVar] = {}
    
    def fresh(self, hint: str = "t") -> ANFVar:
        """Generate a fresh variable name."""
        self.counter += 1
        return ANFVar(f"${hint}{self.counter}")
    
    def push(self, atom: ANFAtom) -> None:
        """Push an atomic value onto the stack."""
        self.stack.append(atom)
    
    def pop(self) -> ANFAtom:
        """Pop and return the top of stack."""
        if not self.stack:
            # Return a placeholder for empty stack (shouldn't happen in valid bytecode)
            return ANFAtom(ANFVar("$empty"))
        return self.stack.pop()
    
    def pop_n(self, n: int) -> List[ANFAtom]:
        """Pop n items, return in original push order."""
        if n == 0:
            return []
        result = self.stack[-n:]
        self.stack = self.stack[:-n]
        return result
    
    def bind(self, rhs: ANFExpr, hint: str = "t") -> ANFAtom:
        """Create a let-binding and return the bound variable as an atom."""
        v = self.fresh(hint)
        self.bindings.append((v, rhs))
        return ANFAtom(v)
    
    def process(self, code: Optional[CodeType] = None) -> Tuple[List[Tuple[ANFVar, ANFExpr]], List[ANFAtom]]:
        """
        Transform bytecode to ANF bindings.
        
        Returns (bindings, final_stack).
        """
        if code is None:
            code = self.code
        if code is None:
            raise ValueError("No code object provided")
        
        for instr in dis.Bytecode(code):
            self.step(instr)
        
        return self.bindings, self.stack
    
    def step(self, instr) -> Optional[ANFTerminator]:
        """
        Process one bytecode instruction.
        
        Returns a terminator if this instruction ends the block.
        """
        op = instr.opname
        arg = instr.argval
        
        # === LOADS (push) ===
        if op == 'LOAD_CONST':
            self.push(ANFAtom(arg))
        
        elif op in ('LOAD_FAST', 'LOAD_FAST_CHECK', 'LOAD_FAST_BORROW'):
            # LOAD_FAST_BORROW (3.14): borrowed ref, same ANF semantics
            v = self.locals_map.get(arg, ANFVar(arg))
            self.push(ANFAtom(v))
        
        elif op in ('LOAD_FAST_LOAD_FAST', 'LOAD_FAST_BORROW_LOAD_FAST_BORROW'):
            # Superinstruction (3.13/3.14): pushes two locals
            # argval = (name1, name2); name1 pushed first (deeper), name2 on top
            name1, name2 = arg
            v1 = self.locals_map.get(name1, ANFVar(name1))
            v2 = self.locals_map.get(name2, ANFVar(name2))
            self.push(ANFAtom(v1))
            self.push(ANFAtom(v2))
        
        elif op == 'LOAD_SMALL_INT':
            # 3.14: optimized small integer load (0-255)
            self.push(ANFAtom(arg))
        
        elif op == 'LOAD_GLOBAL':
            atom = self.bind(ANFPrim('global', [ANFAtom(arg)]), hint='g')
            self.push(atom)
        
        elif op == 'LOAD_ATTR':
            obj = self.pop()
            atom = self.bind(ANFPrim('getattr', [obj, ANFAtom(arg)]), hint='a')
            self.push(atom)
        
        elif op == 'LOAD_METHOD':
            # Python 3.11+: similar to LOAD_ATTR but for methods
            obj = self.pop()
            atom = self.bind(ANFPrim('getmethod', [obj, ANFAtom(arg)]), hint='m')
            self.push(ANFAtom(None))  # NULL or bound method marker
            self.push(atom)
        
        elif op == 'LOAD_NAME':
            atom = self.bind(ANFPrim('name', [ANFAtom(arg)]), hint='n')
            self.push(atom)
        
        elif op == 'LOAD_DEREF':
            atom = self.bind(ANFPrim('deref', [ANFAtom(arg)]), hint='d')
            self.push(atom)
        
        # === STORES (pop + bind to name) ===
        elif op == 'STORE_FAST':
            val = self.pop()
            v = ANFVar(arg)
            self.locals_map[arg] = v
            self.bindings.append((v, val))
        
        elif op == 'STORE_FAST_STORE_FAST':
            # Superinstruction (3.13): pops TOS → argval[0], TOS-1 → argval[1]
            name1, name2 = arg
            val1 = self.pop()
            val2 = self.pop()
            v1 = ANFVar(name1)
            v2 = ANFVar(name2)
            self.locals_map[name1] = v1
            self.locals_map[name2] = v2
            self.bindings.append((v1, val1))
            self.bindings.append((v2, val2))
        
        elif op == 'STORE_FAST_LOAD_FAST':
            # Superinstruction (3.13): stores TOS → argval[0], loads argval[1]
            name_store, name_load = arg
            val = self.pop()
            v_store = ANFVar(name_store)
            self.locals_map[name_store] = v_store
            self.bindings.append((v_store, val))
            v_load = self.locals_map.get(name_load, ANFVar(name_load))
            self.push(ANFAtom(v_load))
        
        elif op == 'STORE_NAME':
            val = self.pop()
            self.bindings.append((ANFVar(arg), ANFPrim('store_name', [val])))
        
        elif op == 'STORE_GLOBAL':
            val = self.pop()
            self.bindings.append((ANFVar(f"${arg}"), ANFPrim('store_global', [ANFAtom(arg), val])))
        
        elif op == 'STORE_ATTR':
            val = self.pop()
            obj = self.pop()
            self.bindings.append((self.fresh('sa'), ANFPrim('setattr', [obj, ANFAtom(arg), val])))
        
        elif op == 'STORE_SUBSCR':
            val = self.pop()
            key = self.pop()
            obj = self.pop()
            self.bindings.append((self.fresh('ss'), ANFPrim('setitem', [obj, key, val])))
        
        # === BINARY OPS ===
        elif op == 'BINARY_OP':
            b = self.pop()
            a = self.pop()
            # arg is the operation code, need to decode
            op_names = {
                0: '+', 1: '&', 2: '//', 3: '<<', 4: '@', 5: '*',
                6: '%', 7: '|', 8: '**', 9: '>>', 10: '-', 11: '/',
                12: '^', 13: '+=', 14: '&=', 15: '//=', 16: '<<=',
                17: '@=', 18: '*=', 19: '%=', 20: '|=', 21: '**=',
                22: '>>=', 23: '-=', 24: '/=', 25: '^=',
            }
            op_sym = op_names.get(instr.arg, f'binop{instr.arg}')
            self.push(self.bind(ANFPrim(op_sym, [a, b]), hint='b'))
        
        elif op.startswith('BINARY_'):
            b = self.pop()
            a = self.pop()
            op_map = {
                'BINARY_ADD': '+', 'BINARY_SUBTRACT': '-',
                'BINARY_MULTIPLY': '*', 'BINARY_TRUE_DIVIDE': '/',
                'BINARY_FLOOR_DIVIDE': '//', 'BINARY_MODULO': '%',
                'BINARY_POWER': '**', 'BINARY_SUBSCR': '[]',
                'BINARY_AND': '&', 'BINARY_OR': '|', 'BINARY_XOR': '^',
                'BINARY_LSHIFT': '<<', 'BINARY_RSHIFT': '>>',
                'BINARY_MATRIX_MULTIPLY': '@',
            }
            bin_sym = op_map.get(op)
            prim = ANFPrim(bin_sym if bin_sym is not None else op, [a, b])
            self.push(self.bind(prim, hint='b'))
        
        # === UNARY OPS ===
        elif op.startswith('UNARY_'):
            a = self.pop()
            op_map = {
                'UNARY_NOT': 'not', 'UNARY_NEGATIVE': '-',
                'UNARY_POSITIVE': '+', 'UNARY_INVERT': '~',
            }
            un_sym = op_map.get(op)
            prim = ANFPrim(un_sym if un_sym is not None else op, [a])
            self.push(self.bind(prim, hint='u'))
        
        # === COMPARE ===
        elif op == 'COMPARE_OP':
            b = self.pop()
            a = self.pop()
            cmp_ops = ['<', '<=', '==', '!=', '>', '>=']
            # arg encodes the comparison
            cmp_name = cmp_ops[instr.arg % len(cmp_ops)] if isinstance(instr.arg, int) else str(arg)
            self.push(self.bind(ANFPrim(f'cmp:{cmp_name}', [a, b]), hint='c'))
        
        elif op == 'IS_OP':
            b = self.pop()
            a = self.pop()
            prim_name = 'is-not' if instr.arg else 'is'
            self.push(self.bind(ANFPrim(prim_name, [a, b]), hint='c'))
        
        elif op == 'CONTAINS_OP':
            b = self.pop()
            a = self.pop()
            prim_name = 'not-in' if instr.arg else 'in'
            self.push(self.bind(ANFPrim(prim_name, [a, b]), hint='c'))
        
        # === CALLS ===
        elif op == 'CALL':
            argc = instr.arg
            args = self.pop_n(argc)
            func = self.pop()
            # Pop the NULL that PUSH_NULL put there (Python 3.11+)
            if self.stack and self.stack[-1].value is None:
                self.pop()
            result = self.bind(ANFCall(func, args), hint='r')
            self.push(result)
        
        elif op == 'CALL_FUNCTION':
            argc = instr.arg
            args = self.pop_n(argc)
            func = self.pop()
            result = self.bind(ANFCall(func, args), hint='r')
            self.push(result)
        
        elif op == 'CALL_FUNCTION_KW':
            # Top of stack is tuple of keyword names
            kw_names = self.pop()
            argc = instr.arg
            args = self.pop_n(argc)
            func = self.pop()
            result = self.bind(ANFCall(func, args), hint='r')
            self.push(result)
        
        elif op == 'CALL_METHOD':
            argc = instr.arg
            args = self.pop_n(argc)
            method = self.pop()
            self_or_null = self.pop()
            result = self.bind(ANFCall(method, [self_or_null] + args), hint='r')
            self.push(result)
        
        # === BUILD STRUCTURES ===
        elif op == 'BUILD_LIST':
            elems = self.pop_n(instr.arg)
            self.push(self.bind(ANFPrim('list', elems), hint='l'))
        
        elif op == 'BUILD_TUPLE':
            elems = self.pop_n(instr.arg)
            self.push(self.bind(ANFPrim('tuple', elems), hint='tup'))
        
        elif op == 'BUILD_SET':
            elems = self.pop_n(instr.arg)
            self.push(self.bind(ANFPrim('set', elems), hint='s'))
        
        elif op == 'BUILD_MAP':
            # Alternating keys and values
            n = instr.arg * 2
            items = self.pop_n(n)
            self.push(self.bind(ANFPrim('dict', items), hint='d'))
        
        elif op == 'BUILD_CONST_KEY_MAP':
            keys = self.pop()  # tuple of keys
            values = self.pop_n(instr.arg)
            self.push(self.bind(ANFPrim('dict_const_keys', [keys] + values), hint='d'))
        
        elif op == 'BUILD_STRING':
            parts = self.pop_n(instr.arg)
            self.push(self.bind(ANFPrim('build_string', parts), hint='str'))
        
        elif op == 'BUILD_SLICE':
            argc = instr.arg
            args = self.pop_n(argc)
            self.push(self.bind(ANFPrim('slice', args), hint='sl'))
        
        elif op == 'LIST_EXTEND' or op == 'SET_UPDATE' or op == 'DICT_UPDATE':
            val = self.pop()
            # The list/set/dict is at stack position -(arg+1)
            # For simplicity, we model this as a side effect
            self.bindings.append((self.fresh('ext'), ANFPrim(op.lower(), [val])))
        
        # === UNPACKING ===
        elif op == 'UNPACK_SEQUENCE':
            seq = self.pop()
            # CPython pushes in reverse: last element deepest, first on top.
            # After STORE_FAST a; STORE_FAST b; the first pop gets index 0.
            for i in range(instr.arg - 1, -1, -1):
                self.push(self.bind(ANFPrim('unpack', [seq, ANFAtom(i)]), hint='up'))
        
        # === SUBSCRIPT ===
        elif op == 'BINARY_SUBSCR':
            key = self.pop()
            obj = self.pop()
            self.push(self.bind(ANFPrim('getitem', [obj, key]), hint='i'))
        
        # === CONTROL FLOW ===
        elif op == 'RETURN_VALUE':
            val = self.pop()
            self.bindings.append((ANFVar('$return'), val))
            return ANFReturn(val)
        
        elif op == 'RETURN_CONST':
            self.bindings.append((ANFVar('$return'), ANFAtom(arg)))
            return ANFReturn(ANFAtom(arg))
        
        elif op == 'POP_JUMP_IF_FALSE':
            cond = self.pop()
            return ANFBranch(cond, instr.offset + 2, arg)
        
        elif op == 'POP_JUMP_IF_TRUE':
            cond = self.pop()
            return ANFBranch(cond, arg, instr.offset + 2)
        
        elif op == 'POP_JUMP_IF_NONE':
            val = self.pop()
            cond = self.bind(ANFPrim('is', [val, ANFAtom(None)]), hint='c')
            return ANFBranch(cond, arg, instr.offset + 2)
        
        elif op == 'POP_JUMP_IF_NOT_NONE':
            val = self.pop()
            cond = self.bind(ANFPrim('is-not', [val, ANFAtom(None)]), hint='c')
            return ANFBranch(cond, arg, instr.offset + 2)
        
        elif op in ('JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP_ABSOLUTE', 
                    'JUMP_BACKWARD_NO_INTERRUPT'):
            return ANFJump(arg)
        
        # === ITERATION ===
        elif op == 'GET_ITER':
            obj = self.pop()
            self.push(self.bind(ANFPrim('iter', [obj]), hint='it'))
        
        elif op == 'FOR_ITER':
            # Complex: pushes next value or jumps to end
            it = self.pop()
            val = self.bind(ANFPrim('next', [it]), hint='nx')
            self.push(ANFAtom(it.value))  # Re-push iterator
            self.push(val)
        
        elif op == 'END_FOR':
            # Pop iterator
            self.pop()
        
        # === STACK MANIPULATION ===
        elif op == 'POP_TOP':
            self.pop()
        
        elif op == 'DUP_TOP':
            top = self.stack[-1]
            self.push(top)
        
        elif op == 'ROT_TWO':
            a = self.pop()
            b = self.pop()
            self.push(a)
            self.push(b)
        
        elif op == 'ROT_THREE':
            a = self.pop()
            b = self.pop()
            c = self.pop()
            self.push(a)
            self.push(c)
            self.push(b)
        
        elif op == 'COPY':
            # Copy item at position arg to top
            n = instr.arg
            if n > 0 and n <= len(self.stack):
                self.push(self.stack[-n])
        
        elif op == 'SWAP':
            n = instr.arg
            if n > 0 and n <= len(self.stack):
                self.stack[-1], self.stack[-n] = self.stack[-n], self.stack[-1]
        
        # === MISC ===
        elif op == 'RESUME':
            pass  # Entry point marker
        
        elif op == 'PUSH_NULL':
            self.push(ANFAtom(None))
        
        elif op == 'PRECALL':
            pass  # Pre-call setup, no stack effect we need to model
        
        elif op == 'NOP':
            pass
        
        elif op == 'CACHE':
            pass  # Interpreter cache slot
        
        elif op == 'MAKE_FUNCTION':
            # Complex: pops code object and potentially defaults, closure, etc.
            code_obj = self.pop()
            self.push(self.bind(ANFPrim('make_function', [code_obj]), hint='fn'))
        
        elif op == 'LOAD_CLOSURE':
            self.push(self.bind(ANFPrim('closure', [ANFAtom(arg)]), hint='cl'))
        
        elif op == 'LOAD_BUILD_CLASS':
            self.push(self.bind(ANFPrim('build_class', []), hint='bc'))
        
        elif op == 'IMPORT_NAME':
            fromlist = self.pop()
            level = self.pop()
            self.push(self.bind(ANFPrim('import', [ANFAtom(arg), level, fromlist]), hint='imp'))
        
        elif op == 'IMPORT_FROM':
            # TOS is module, import attr from it
            module = self.stack[-1]  # Don't pop
            self.push(self.bind(ANFPrim('import_from', [module, ANFAtom(arg)]), hint='imp'))

        # === 3.12+ opcodes ===
        elif op == 'LOAD_FAST_AND_CLEAR':
            # Load local and set slot to NULL. Used in comprehensions.
            v = self.locals_map.get(arg, ANFVar(arg)) if isinstance(arg, str) else ANFVar(f'${arg}')
            self.push(ANFAtom(v))

        elif op == 'LOAD_SUPER_ATTR':
            # 3.12: super() attribute access
            attr_name = self.pop()
            cls = self.pop()
            self_val = self.pop()
            self.push(self.bind(ANFPrim('super_attr', [self_val, cls, attr_name]), hint='sa'))

        elif op == 'CALL_INTRINSIC_1':
            a = self.pop()
            self.push(self.bind(ANFPrim(f'intrinsic1:{instr.arg}', [a]), hint='intr'))

        elif op == 'CALL_INTRINSIC_2':
            b = self.pop()
            a = self.pop()
            self.push(self.bind(ANFPrim(f'intrinsic2:{instr.arg}', [a, b]), hint='intr'))

        elif op == 'END_SEND':
            # Generator: pop sent value, keep result
            self.pop()

        elif op == 'RETURN_GENERATOR':
            # Marks function as generator; no stack effect for ANF purposes
            pass

        elif op in ('COPY_FREE_VARS', 'MAKE_CELL'):
            pass  # Interpreter bookkeeping, no ANF-visible effect

        elif op in ('PUSH_EXC_INFO', 'POP_EXCEPT', 'CHECK_EXC_MATCH',
                     'BEFORE_WITH', 'CLEANUP_THROW', 'STOPITERATION_ERROR'):
            # Exception handling opcodes. Record but don't model stack
            # effects precisely (requires exception table CFG edges).
            self.bindings.append((self.fresh('exc'), ANFPrim(f'exc:{op}', [])))

        elif op == 'MATCH_SEQUENCE':
            seq = self.pop()
            self.push(self.bind(ANFPrim('match_seq', [seq]), hint='ms'))

        elif op == 'MATCH_MAPPING':
            mapping = self.pop()
            self.push(self.bind(ANFPrim('match_map', [mapping]), hint='mm'))

        elif op == 'MATCH_CLASS':
            # Pops subject + count positional patterns
            nargs = instr.arg
            args = self.pop_n(nargs)
            subject = self.pop()
            self.push(self.bind(ANFPrim('match_class', [subject] + args), hint='mc'))

        elif op == 'MATCH_KEYS':
            keys = self.pop()
            mapping = self.stack[-1] if self.stack else ANFAtom(None)
            self.push(self.bind(ANFPrim('match_keys', [mapping, keys]), hint='mk'))

        elif op == 'BUILD_SLICE':
            argc = instr.arg
            args = self.pop_n(argc)
            self.push(self.bind(ANFPrim('slice', args), hint='sl'))

        # === 3.13+ opcodes ===

        elif op == 'TO_BOOL':
            # 3.13: explicit bool(TOS) conversion
            val = self.pop()
            self.push(self.bind(ANFPrim('bool', [val]), hint='tb'))

        elif op == 'NOT_TAKEN':
            pass  # 3.14: branch hint NOP for monitoring

        elif op == 'POP_ITER':
            # 3.14: pops iterator (replaces POP_TOP after FOR_ITER)
            self.pop()

        elif op == 'CALL_KW':
            # 3.13: call with keyword arguments
            # Stack: callable, self/NULL, positional args..., kw names tuple
            kw_names = self.pop()
            argc = instr.arg
            args = self.pop_n(argc)
            func = self.pop()
            # Pop NULL if present (3.11+ calling convention)
            if self.stack and self.stack[-1].value is None:
                self.pop()
            result = self.bind(ANFCall(func, args), hint='r')
            self.push(result)

        elif op == 'LOAD_COMMON_CONSTANT':
            # 3.14: loads hardcoded constants (e.g. AssertionError)
            self.push(self.bind(ANFPrim('common_const', [ANFAtom(instr.arg)]), hint='cc'))

        elif op == 'LOAD_SPECIAL':
            # 3.14: special method lookup on TOS
            # Pushes method + self/NULL (2 values, net stack effect +1)
            obj = self.pop()
            self.push(self.bind(ANFPrim('special_method', [obj, ANFAtom(instr.arg)]), hint='sp'))
            self.push(ANFAtom(None))  # NULL or self marker

        elif op == 'FORMAT_SIMPLE':
            # 3.13: TOS = TOS.__format__("")
            val = self.pop()
            self.push(self.bind(ANFPrim('format', [val]), hint='fmt'))

        elif op == 'FORMAT_WITH_SPEC':
            # 3.13: spec=pop, val=pop, push val.__format__(spec)
            spec = self.pop()
            val = self.pop()
            self.push(self.bind(ANFPrim('format', [val, spec]), hint='fmt'))

        elif op == 'CONVERT_VALUE':
            # 3.13: convert for f-string (1=str, 2=repr, 3=ascii)
            val = self.pop()
            conv_map = {1: 'str', 2: 'repr', 3: 'ascii'}
            conv_name = conv_map.get(instr.arg, f'convert:{instr.arg}')
            self.push(self.bind(ANFPrim(conv_name, [val]), hint='cv'))

        elif op == 'BINARY_SLICE':
            # 3.12: container[start:end]
            end = self.pop()
            start = self.pop()
            container = self.pop()
            self.push(self.bind(ANFPrim('getslice', [container, start, end]), hint='sl'))

        elif op == 'STORE_SLICE':
            # 3.12: container[start:end] = value
            end = self.pop()
            start = self.pop()
            container = self.pop()
            value = self.pop()
            self.bindings.append((self.fresh('ss'),
                ANFPrim('setslice', [container, start, end, value])))

        elif op == 'BUILD_INTERPOLATION':
            # 3.14 (PEP 750): template string interpolation
            has_spec = instr.arg & 1
            if has_spec:
                fmt_spec = self.pop()
                conversion = self.pop()
                expr_str = self.pop()
                value = self.pop()
                self.push(self.bind(
                    ANFPrim('interpolation', [value, expr_str, conversion, fmt_spec]),
                    hint='interp'))
            else:
                conversion = self.pop()
                expr_str = self.pop()
                value = self.pop()
                self.push(self.bind(
                    ANFPrim('interpolation', [value, expr_str, conversion]),
                    hint='interp'))

        elif op == 'BUILD_TEMPLATE':
            # 3.14 (PEP 750): builds Template from strings + interpolations
            interpolations = self.pop()
            strings = self.pop()
            self.push(self.bind(
                ANFPrim('template', [strings, interpolations]), hint='tmpl'))

        elif op == 'SET_FUNCTION_ATTRIBUTE':
            # 3.13: pops attr value + func, pushes func with attr set
            attr_val = self.pop()
            func = self.pop()
            self.push(self.bind(
                ANFPrim('set_func_attr', [func, ANFAtom(instr.arg), attr_val]),
                hint='fn'))

        elif op == 'EXIT_INIT_CHECK':
            # 3.12: pops TOS, checks it's None (__init__ return check)
            self.pop()

        elif op == 'LOAD_LOCALS':
            # 3.13: pushes locals() dict
            self.push(self.bind(ANFPrim('locals', []), hint='loc'))

        elif op == 'LOAD_FROM_DICT_OR_DEREF':
            # 3.12: pops mapping, looks up name, falls back to deref
            mapping = self.pop()
            self.push(self.bind(
                ANFPrim('from_dict_or_deref', [mapping, ANFAtom(arg)]), hint='dd'))

        elif op == 'LOAD_FROM_DICT_OR_GLOBALS':
            # 3.12: pops mapping, looks up name, falls back to globals
            mapping = self.pop()
            self.push(self.bind(
                ANFPrim('from_dict_or_globals', [mapping, ANFAtom(arg)]), hint='dg'))

        elif op == 'LIST_APPEND':
            # Comprehension: list.append(STACK[-i], TOS)
            item = self.pop()
            self.bindings.append((self.fresh('la'),
                ANFPrim('list_append', [ANFAtom(instr.arg), item])))

        elif op == 'SET_ADD':
            # Comprehension: set.add(STACK[-i], TOS)
            item = self.pop()
            self.bindings.append((self.fresh('sa'),
                ANFPrim('set_add', [ANFAtom(instr.arg), item])))

        elif op == 'MAP_ADD':
            # Comprehension: dict[key] = value
            value = self.pop()
            key = self.pop()
            self.bindings.append((self.fresh('ma'),
                ANFPrim('map_add', [ANFAtom(instr.arg), key, value])))

        elif op == 'DICT_MERGE':
            # Like DICT_UPDATE but raises on duplicate keys
            val = self.pop()
            self.bindings.append((self.fresh('dm'), ANFPrim('dict_merge', [val])))

        elif op == 'UNPACK_EX':
            # Unpack with starred target: a, *b, c = iterable
            # Low byte = count before star, high byte = count after star
            seq = self.pop()
            before = instr.arg & 0xFF
            after = (instr.arg >> 8) & 0xFF
            total = before + 1 + after  # +1 for the starred list
            for i in range(total - 1, -1, -1):
                self.push(self.bind(
                    ANFPrim('unpack_ex', [seq, ANFAtom(i), ANFAtom(before)]),
                    hint='ux'))

        elif op == 'STORE_DEREF':
            # Store into closure cell
            val = self.pop()
            self.bindings.append((self.fresh('sd'),
                ANFPrim('store_deref', [ANFAtom(arg), val])))

        elif op in ('DELETE_FAST', 'DELETE_NAME', 'DELETE_GLOBAL',
                     'DELETE_DEREF'):
            # Deletes — no stack effect, record as side effect
            self.bindings.append((self.fresh('del'),
                ANFPrim(f'delete:{op}', [ANFAtom(arg)])))

        elif op == 'DELETE_ATTR':
            # Pops object, deletes attribute
            obj = self.pop()
            self.bindings.append((self.fresh('da'),
                ANFPrim('delattr', [obj, ANFAtom(arg)])))

        elif op == 'DELETE_SUBSCR':
            # Pops key and object
            key = self.pop()
            obj = self.pop()
            self.bindings.append((self.fresh('ds'),
                ANFPrim('delitem', [obj, key])))

        elif op == 'STORE_FAST_MAYBE_NULL':
            # Pseudo-op (3.13): same as STORE_FAST
            val = self.pop()
            v = ANFVar(arg) if isinstance(arg, str) else self.fresh('sm')
            if isinstance(arg, str):
                self.locals_map[arg] = v
            self.bindings.append((v, val))

        elif op == 'CALL_FUNCTION_EX':
            # Call with *args and optionally **kwargs
            if instr.arg & 1:
                kwargs = self.pop()
                args_tuple = self.pop()
                func = self.pop()
                result = self.bind(
                    ANFPrim('call_ex', [func, args_tuple, kwargs]), hint='r')
            else:
                args_tuple = self.pop()
                func = self.pop()
                result = self.bind(
                    ANFPrim('call_ex', [func, args_tuple]), hint='r')
            # Pop NULL if present
            if self.stack and self.stack[-1].value is None:
                self.pop()
            self.push(result)

        elif op in ('GET_AITER', 'GET_ANEXT', 'GET_AWAITABLE',
                     'GET_YIELD_FROM_ITER'):
            # Async/generator iteration setup — replaces TOS
            obj = self.pop()
            self.push(self.bind(ANFPrim(op.lower(), [obj]), hint='aw'))

        elif op == 'YIELD_VALUE':
            val = self.pop()
            self.push(self.bind(ANFPrim('yield', [val]), hint='yv'))

        elif op == 'SETUP_ANNOTATIONS':
            pass  # 3.x: sets up __annotations__ dict, no stack effect

        elif op in ('END_ASYNC_FOR', 'WITH_EXCEPT_START', 'BEFORE_WITH'):
            # Complex exception/context opcodes — record as side effect
            self.bindings.append((self.fresh('ctx'),
                ANFPrim(f'ctx:{op}', [])))

        elif op == 'RAISE_VARARGS':
            argc = instr.arg
            args = self.pop_n(argc)
            self.bindings.append((self.fresh('raise'),
                ANFPrim('raise', args)))

        elif op == 'RERAISE':
            pass  # Re-raises current exception

        else:
            # Unknown opcode: record it for completeness
            self.bindings.append((self.fresh('unk'), ANFPrim(f'?{op}', [ANFAtom(instr.arg)])))

        # Stack depth validation
        if self.code is not None and len(self.stack) > self.code.co_stacksize + 1:
            # +1 for tolerance on edge cases (NULL sentinels, etc.)
            pass  # Could warn; for now just track

        return None


def bytecode_to_anf(code: CodeType) -> List[Tuple[ANFVar, ANFExpr]]:
    """
    Convert a code object to ANF bindings.
    
    This is the main entry point for simple usage.
    """
    converter = StackToANF(code)
    bindings, _ = converter.process()
    return bindings


def print_anf(bindings: List[Tuple[ANFVar, ANFExpr]]) -> None:
    """Pretty-print ANF bindings."""
    for var, rhs in bindings:
        print(f"let {var} = {rhs}")
