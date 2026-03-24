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
    ANFBody, ANFBinding, ANFJoin, JoinField, JoinParam,
    ANFBranch, ANFJump, ANFReturn, ANFInvokeJoin,
    ANFExpr, ANFTerminator,
)


@dataclass
class BasicBlock:
    """
    A basic block in the CFG.
    
    Contains straight-line ANF bindings and a terminator.
    """
    label: int  # Bytecode offset of first instruction
    bindings: List[ANFBinding] = field(default_factory=list)
    terminator: Optional[ANFTerminator] = None
    predecessors: List[int] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)
    
    def add_binding(self, var: ANFVar, rhs: ANFExpr) -> None:
        self.bindings.append(ANFBinding(var, rhs))
    
    def __repr__(self) -> str:
        lines = [f"BB{self.label}:"]
        for binding in self.bindings:
            lines.append(f"  {binding}")
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
            
            if op in self.JUMPS:
                # Jump target is a leader (only for actual jumps, not terminators)
                if instr.argval is not None and isinstance(instr.argval, int):
                    self.leaders.add(instr.argval)
                
                # Fall-through (next instruction) is a leader
                if i + 1 < len(self.instructions):
                    self.leaders.add(self.instructions[i + 1].offset)
            elif op in self.TERMINATORS:
                # Terminators end blocks but don't have jump targets
                # (RETURN_CONST argval is the constant value, not an offset!)
                if i + 1 < len(self.instructions):
                    self.leaders.add(self.instructions[i + 1].offset)
        
        return sorted(self.leaders)
    
    def build(self) -> Dict[int, BasicBlock]:
        """Build the CFG and return the blocks."""
        leaders = self.find_leaders()

        # Create blocks
        for leader in leaders:
            self.blocks[leader] = BasicBlock(label=leader)

        sorted_leaders = sorted(leaders)

        def add_edge(src: int, dst: int) -> None:
            if dst not in self.blocks[src].successors:
                self.blocks[src].successors.append(dst)
            if src not in self.blocks[dst].predecessors:
                self.blocks[dst].predecessors.append(src)

        # Compute edges from each block's terminal instruction.
        for i, label in enumerate(sorted_leaders):
            next_leader = sorted_leaders[i + 1] if i + 1 < len(sorted_leaders) else None

            block_instructions = [
                instr for instr in self.instructions
                if label <= instr.offset < (next_leader if next_leader is not None else 2**31)
            ]
            if not block_instructions:
                continue

            last_instr = block_instructions[-1]
            op = last_instr.opname

            if op in self.TERMINATORS:
                continue

            if op in self.JUMPS:
                target = last_instr.argval
                if target is not None and isinstance(target, int) and target in self.blocks:
                    add_edge(label, target)

                # Conditional jumps also fall through to the next block.
                if op not in ('JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP_ABSOLUTE',
                              'JUMP_BACKWARD_NO_INTERRUPT') and next_leader is not None:
                    add_edge(label, next_leader)
                continue

            # Straight-line block: execution falls through to the next block.
            if next_leader is not None:
                add_edge(label, next_leader)

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
        self.locals_map: Dict[str, ANFAtom] = {}
    
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

    def _instructions_by_block(self, code: CodeType, cfg: Dict[int, BasicBlock]) -> Dict[int, List[Any]]:
        """Group bytecode instructions by basic block label."""
        instructions = list(dis.Bytecode(code))
        sorted_labels = sorted(cfg.keys())
        result: Dict[int, List[Any]] = {}
        for i, label in enumerate(sorted_labels):
            end = sorted_labels[i + 1] if i + 1 < len(sorted_labels) else 2**31
            result[label] = [instr for instr in instructions if label <= instr.offset < end]
        return result

    def _run_block_with_state(
        self,
        instructions: List[Any],
        stack: List[ANFAtom],
        locals_map: Dict[str, ANFAtom],
    ) -> Tuple[List[ANFBinding], List[ANFAtom], Dict[str, ANFAtom], Optional[ANFTerminator]]:
        """Run one block under an explicit stack/local state."""
        saved_bindings = self.bindings
        saved_stack = self.stack
        saved_locals = self.locals_map

        self.bindings = []
        self.stack = list(stack)
        self.locals_map = dict(locals_map)

        terminator: Optional[ANFTerminator] = None
        for i, instr in enumerate(instructions):
            next_offset = instructions[i + 1].offset if i + 1 < len(instructions) else None
            terminator = self.step(instr, next_offset=next_offset)
            if terminator is not None:
                break

        block_bindings = [ANFBinding(var, rhs) for var, rhs in self.bindings]
        block_stack = list(self.stack)
        block_locals = dict(self.locals_map)

        self.bindings = saved_bindings
        self.stack = saved_stack
        self.locals_map = saved_locals

        return block_bindings, block_stack, block_locals, terminator

    def _build_join_spec(
        self,
        label: int,
        preds: List[int],
        exit_stacks: Dict[int, List[ANFAtom]],
        exit_locals: Dict[int, Dict[str, ANFAtom]],
        predecessor_states: Dict[int, Dict[int, Any]],
        existing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build or refine join parameters for a merge block."""
        known_preds = [pred for pred in preds if pred in exit_locals]
        pred_state_map = predecessor_states.get(label, {})

        if len(known_preds) == len(preds) and known_preds:
            all_local_names = sorted({name for pred in preds for name in exit_locals[pred].keys()})
            local_names = []
            for name in all_local_names:
                values = [exit_locals[pred].get(name, ANFAtom(ANFVar(name))) for pred in preds]
                if any(value != values[0] for value in values[1:]):
                    local_names.append(name)

            stack_depth = max(len(exit_stacks.get(pred, [])) for pred in preds)
            stack_indices = []
            for i in range(stack_depth):
                values = [
                    exit_stacks.get(pred, [])[i] if i < len(exit_stacks.get(pred, [])) else ANFAtom(ANFVar(f"$stack{i}"))
                    for pred in preds
                ]
                if any(value != values[0] for value in values[1:]):
                    stack_indices.append(i)
        else:
            local_names = sorted({
                name
                for pred_map in [pred_state_map]
                for state in pred_map.values()
                for name in state.locals_ann.keys()
            } | {
                name
                for pred in known_preds
                for name in exit_locals[pred].keys()
            })
            stack_depth = 0
            if pred_state_map:
                stack_depth = max(stack_depth, max(len(state.stack.items) for state in pred_state_map.values()))
            if known_preds:
                stack_depth = max(stack_depth, max(len(exit_stacks.get(pred, [])) for pred in known_preds))
            stack_indices = list(range(stack_depth))

        existing_local_vars = (existing or {}).get('local_vars', {})
        existing_stack_vars = (existing or {}).get('stack_vars', {})

        local_vars = {
            name: existing_local_vars.get(name, self.fresh(f"j{label}_{name}"))
            for name in local_names
        }
        stack_vars = {
            i: existing_stack_vars.get(i, self.fresh(f"j{label}_s{i}"))
            for i in stack_indices
        }

        if known_preds:
            base_pred = known_preds[0]
            env_locals = dict(exit_locals[base_pred])
            env_stack = list(exit_stacks.get(base_pred, []))
        else:
            env_locals = {}
            env_stack = []

        for name, var in local_vars.items():
            env_locals[name] = ANFAtom(var)

        needed_stack_len = max(stack_indices, default=-1) + 1
        while len(env_stack) < needed_stack_len:
            env_stack.append(ANFAtom(ANFVar(f"$stack{len(env_stack)}")))
        for i, var in stack_vars.items():
            env_stack[i] = ANFAtom(var)

        return {
            'join_var': (existing or {}).get('join_var', self.fresh(f"join{label}")),
            'local_names': local_names,
            'stack_indices': stack_indices,
            'local_vars': local_vars,
            'stack_vars': stack_vars,
            'env_locals': env_locals,
            'env_stack': env_stack,
        }

    def process_cfg(self, code: Optional[CodeType] = None, max_iterations: int = 4) -> Dict[int, BasicBlock]:
        """Structured, block-aware ANF transform with explicit join-field invocation."""
        if code is None:
            code = self.code
        if code is None:
            raise ValueError("No code object provided")

        cfg = CFGBuilder(code).build()
        if not cfg:
            return {}

        instructions_by_block = self._instructions_by_block(code, cfg)

        predecessor_states: Dict[int, Dict[int, Any]] = {}
        try:
            from .interpreter import AbstractInterpreter
            from .builtin_lattices import TypeLattice
            from .builtin_transfers import register_builtin_transfers
            lattice = TypeLattice()
            register_builtin_transfers(lattice)
            analysis = AbstractInterpreter(lattice).analyze_cfg_detailed(code)
            predecessor_states = analysis.predecessor_states
        except Exception:
            predecessor_states = {}

        merge_labels = {label for label, block in cfg.items() if len(block.predecessors) > 1}
        join_specs: Dict[int, Dict[str, Any]] = {}
        compiled_blocks: Dict[int, BasicBlock] = {}

        for _ in range(max_iterations):
            exit_stacks: Dict[int, List[ANFAtom]] = {}
            exit_locals: Dict[int, Dict[str, ANFAtom]] = {}
            entry_stacks: Dict[int, List[ANFAtom]] = {0: []}
            entry_locals: Dict[int, Dict[str, ANFAtom]] = {0: {}}
            compiled_blocks = {}

            changed = False

            for label in sorted(cfg.keys()):
                block = cfg[label]
                block_out = BasicBlock(
                    label=label,
                    predecessors=list(block.predecessors),
                    successors=list(block.successors),
                )

                if label in merge_labels:
                    spec = self._build_join_spec(
                        label,
                        list(block.predecessors),
                        exit_stacks,
                        exit_locals,
                        predecessor_states,
                        existing=join_specs.get(label),
                    )
                    if join_specs.get(label) != spec:
                        changed = True
                    join_specs[label] = spec

                    generic_bindings, generic_stack, generic_locals, generic_term = self._run_block_with_state(
                        instructions_by_block[label],
                        spec['env_stack'],
                        spec['env_locals'],
                    )

                    fields: List[JoinField] = []
                    for pred in block.predecessors:
                        pred_state = predecessor_states.get(label, {}).get(pred)
                        params: List[JoinParam] = []
                        for name in spec['local_names']:
                            ann = pred_state.locals_ann.get(name) if pred_state is not None else None
                            params.append(JoinParam(spec['local_vars'][name], ann=ann))
                        for i in spec['stack_indices']:
                            ann = None
                            if pred_state is not None and i < len(pred_state.stack.items):
                                ann = pred_state.stack.items[i].ann
                            params.append(JoinParam(spec['stack_vars'][i], ann=ann))
                        fields.append(JoinField(
                            label=pred,
                            params=params,
                            body=ANFBody(bindings=list(generic_bindings), terminator=generic_term),
                        ))

                    block_out.add_binding(spec['join_var'], ANFJoin(spec['join_var'], fields))
                    block_out.terminator = None
                    compiled_blocks[label] = block_out
                    exit_stacks[label] = generic_stack
                    exit_locals[label] = generic_locals

                    for succ in block.successors:
                        entry_stacks.setdefault(succ, list(generic_stack))
                        entry_locals.setdefault(succ, dict(generic_locals))
                    continue

                in_stack = entry_stacks.get(label, [])
                in_locals = entry_locals.get(label, {})
                block_bindings, out_stack, out_locals, terminator = self._run_block_with_state(
                    instructions_by_block[label],
                    in_stack,
                    in_locals,
                )
                block_out.bindings = block_bindings
                block_out.terminator = terminator
                exit_stacks[label] = out_stack
                exit_locals[label] = out_locals

                if len(block.successors) == 1 and block.successors[0] in merge_labels:
                    succ = block.successors[0]
                    spec = join_specs.get(succ)
                    if spec is not None:
                        args = [
                            out_locals.get(name, ANFAtom(ANFVar(name)))
                            for name in spec['local_names']
                        ] + [
                            out_stack[i] if i < len(out_stack) else ANFAtom(ANFVar(f"$stack{i}"))
                            for i in spec['stack_indices']
                        ]
                        block_out.terminator = ANFInvokeJoin(spec['join_var'], label, args)
                elif isinstance(terminator, ANFBranch):
                    true_label = terminator.true_label
                    false_label = terminator.false_label
                    last_op = instructions_by_block[label][-1].opname if instructions_by_block[label] else None

                    true_stack = list(out_stack)
                    false_stack = list(out_stack)
                    if last_op == 'FOR_ITER':
                        false_stack = list(in_stack[:-1]) if in_stack else []

                    if true_label not in merge_labels:
                        entry_stacks.setdefault(true_label, true_stack)
                        entry_locals.setdefault(true_label, dict(out_locals))
                    if false_label not in merge_labels:
                        entry_stacks.setdefault(false_label, false_stack)
                        entry_locals.setdefault(false_label, dict(out_locals))
                elif isinstance(terminator, ANFJump):
                    succ = terminator.label
                    if succ not in merge_labels:
                        entry_stacks.setdefault(succ, list(out_stack))
                        entry_locals.setdefault(succ, dict(out_locals))
                elif terminator is None and block.successors:
                    succ = block.successors[0]
                    if succ not in merge_labels:
                        entry_stacks.setdefault(succ, list(out_stack))
                        entry_locals.setdefault(succ, dict(out_locals))

                compiled_blocks[label] = block_out

            if not changed:
                break

        return compiled_blocks
    
    def process(self, code: Optional[CodeType] = None) -> Tuple[List[Tuple[ANFVar, ANFExpr]], List[ANFAtom]]:
        """
        Transform bytecode to ANF bindings.
        
        Returns (bindings, final_stack).
        """
        if code is None:
            code = self.code
        if code is None:
            raise ValueError("No code object provided")
        
        instructions = list(dis.Bytecode(code))
        for i, instr in enumerate(instructions):
            # Compute next instruction offset for branch fallthrough calculation
            next_offset = instructions[i + 1].offset if i + 1 < len(instructions) else None
            self.step(instr, next_offset=next_offset)
        
        return self.bindings, self.stack
    
    def step(self, instr, next_offset: Optional[int] = None) -> Optional[ANFTerminator]:
        """
        Process one bytecode instruction.
        
        Args:
            instr: The bytecode instruction to process
            next_offset: Offset of the next instruction (for fallthrough branches)
        
        Returns a terminator if this instruction ends the block.
        """
        op = instr.opname
        arg = instr.argval
        
        # === LOADS (push) ===
        if op == 'LOAD_CONST':
            self.push(ANFAtom(arg))
        
        elif op in ('LOAD_FAST', 'LOAD_FAST_CHECK', 'LOAD_FAST_BORROW'):
            # LOAD_FAST_BORROW (3.14): borrowed ref, same ANF semantics
            v = self.locals_map.get(arg, ANFAtom(ANFVar(arg)))
            self.push(v)
        
        elif op in ('LOAD_FAST_LOAD_FAST', 'LOAD_FAST_BORROW_LOAD_FAST_BORROW'):
            # Superinstruction (3.13/3.14): pushes two locals
            # argval = (name1, name2); name1 pushed first (deeper), name2 on top
            name1, name2 = arg
            v1 = self.locals_map.get(name1, ANFAtom(ANFVar(name1)))
            v2 = self.locals_map.get(name2, ANFAtom(ANFVar(name2)))
            self.push(v1)
            self.push(v2)
        
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
            self.locals_map[arg] = val
            self.bindings.append((v, val))
        
        elif op == 'STORE_FAST_STORE_FAST':
            # Superinstruction (3.13): pops TOS → argval[0], TOS-1 → argval[1]
            name1, name2 = arg
            val1 = self.pop()
            val2 = self.pop()
            v1 = ANFVar(name1)
            v2 = ANFVar(name2)
            self.locals_map[name1] = val1
            self.locals_map[name2] = val2
            self.bindings.append((v1, val1))
            self.bindings.append((v2, val2))
        
        elif op == 'STORE_FAST_LOAD_FAST':
            # Superinstruction (3.13): stores TOS → argval[0], loads argval[1]
            name_store, name_load = arg
            val = self.pop()
            v_store = ANFVar(name_store)
            self.locals_map[name_store] = val
            self.bindings.append((v_store, val))
            v_load = self.locals_map.get(name_load, ANFAtom(ANFVar(name_load)))
            self.push(v_load)
        
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

        elif op.startswith('INPLACE_'):
            b = self.pop()
            a = self.pop()
            op_map = {
                'INPLACE_ADD': '+', 'INPLACE_SUBTRACT': '-',
                'INPLACE_MULTIPLY': '*', 'INPLACE_TRUE_DIVIDE': '/',
                'INPLACE_FLOOR_DIVIDE': '//', 'INPLACE_MODULO': '%',
                'INPLACE_POWER': '**', 'INPLACE_AND': '&',
                'INPLACE_OR': '|', 'INPLACE_XOR': '^',
                'INPLACE_LSHIFT': '<<', 'INPLACE_RSHIFT': '>>',
                'INPLACE_MATRIX_MULTIPLY': '@',
            }
            prim = ANFPrim(op_map.get(op, op), [a, b])
            self.push(self.bind(prim, hint='i'))
        
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
            # Fallthrough is next instruction, not hardcoded +2 (CACHE entries may intervene)
            fallthrough = next_offset if next_offset is not None else instr.offset + 2
            return ANFBranch(cond, fallthrough, arg)
        
        elif op == 'POP_JUMP_IF_TRUE':
            cond = self.pop()
            fallthrough = next_offset if next_offset is not None else instr.offset + 2
            return ANFBranch(cond, arg, fallthrough)
        
        elif op == 'POP_JUMP_IF_NONE':
            val = self.pop()
            cond = self.bind(ANFPrim('is', [val, ANFAtom(None)]), hint='c')
            fallthrough = next_offset if next_offset is not None else instr.offset + 2
            return ANFBranch(cond, arg, fallthrough)
        
        elif op == 'POP_JUMP_IF_NOT_NONE':
            val = self.pop()
            cond = self.bind(ANFPrim('is-not', [val, ANFAtom(None)]), hint='c')
            fallthrough = next_offset if next_offset is not None else instr.offset + 2
            return ANFBranch(cond, arg, fallthrough)
        
        elif op in ('JUMP_FORWARD', 'JUMP_BACKWARD', 'JUMP_ABSOLUTE', 
                    'JUMP_BACKWARD_NO_INTERRUPT'):
            return ANFJump(arg)
        
        # === ITERATION ===
        elif op == 'GET_ITER':
            obj = self.pop()
            self.push(self.bind(ANFPrim('iter', [obj]), hint='it'))
        
        elif op == 'FOR_ITER':
            # Iterator loop header: on continue, keep iterator + next value;
            # on exhaustion, branch to the loop exit.
            it = self.pop()
            has_next = self.bind(ANFPrim('iter_has_next', [it]), hint='fi')
            val = self.bind(ANFPrim('next', [it]), hint='nx')
            self.push(it)   # Continue path keeps iterator live
            self.push(val)  # ...and exposes next item
            fallthrough = next_offset if next_offset is not None else instr.offset + 2
            return ANFBranch(has_next, fallthrough, arg)
        
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
            v = self.locals_map.get(arg, ANFAtom(ANFVar(arg))) if isinstance(arg, str) else ANFAtom(ANFVar(f'${arg}'))
            self.push(v)

        elif op == 'LOAD_SUPER_ATTR':
            # 3.12: super() attribute access
            # Stack: [global_super, __class__, self] -> pops 3, attr name is in argval
            # See CPython ceval.c: LOAD_SUPER_ATTR pops super, class, self; attr from oparg
            self_val = self.pop()   # TOS: self instance
            cls = self.pop()        # TOS1: __class__
            super_fn = self.pop()   # TOS2: super (the builtin)
            attr_name = ANFAtom(arg)  # attr name from instr.argval
            self.push(self.bind(ANFPrim('super_attr', [super_fn, cls, self_val, attr_name]), hint='sa'))

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
            # Stack: callable, self/NULL, positional args..., keyword args..., kw_names_tuple
            # The kw_names tuple is pushed via LOAD_CONST before CALL_KW
            # instr.arg is total argument count (positional + keyword)
            kw_names_atom = self.pop()  # Pop the kw_names tuple from stack
            argc = instr.arg
            
            # Extract the actual tuple from the ANFAtom
            kw_names_tuple = kw_names_atom.value if isinstance(kw_names_atom, ANFAtom) else None
            if isinstance(kw_names_tuple, tuple):
                n_kwargs = len(kw_names_tuple)
            else:
                # Couldn't extract tuple - treat all as positional
                n_kwargs = 0
                kw_names_tuple = ()
            
            n_positional = argc - n_kwargs
            
            # Pop all args (keyword args are on top of stack, then positional)
            all_args = self.pop_n(argc)
            positional_args = all_args[:n_positional]
            kw_arg_values = all_args[n_positional:]
            
            func = self.pop()
            # Pop NULL if present (3.11+ calling convention)
            if self.stack and self.stack[-1].value is None:
                self.pop()
            
            # Build KWArg list from names and values
            from .anf import KWArg
            kwargs = [KWArg(name, val) for name, val in zip(kw_names_tuple, kw_arg_values)] if kw_names_tuple else None
            
            result = self.bind(ANFCall(func, positional_args, kwargs=kwargs), hint='r')
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
            # Deletes: no stack effect, record as side effect
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
                self.locals_map[arg] = val
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
            # Async/generator iteration setup: replaces TOS
            obj = self.pop()
            self.push(self.bind(ANFPrim(op.lower(), [obj]), hint='aw'))

        elif op == 'YIELD_VALUE':
            val = self.pop()
            self.push(self.bind(ANFPrim('yield', [val]), hint='yv'))

        elif op == 'SETUP_ANNOTATIONS':
            pass  # 3.x: sets up __annotations__ dict, no stack effect

        elif op in ('END_ASYNC_FOR', 'WITH_EXCEPT_START', 'BEFORE_WITH'):
            # Complex exception/context opcodes: record as side effect
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


def bytecode_to_anf_cfg(code: CodeType) -> Dict[int, BasicBlock]:
    """Convert a code object to structured CFG-shaped ANF blocks."""
    converter = StackToANF(code)
    return converter.process_cfg()


def print_anf(bindings: List[Tuple[ANFVar, ANFExpr]]) -> None:
    """Pretty-print ANF bindings."""
    for var, rhs in bindings:
        print(f"let {var} = {rhs}")


def print_anf_cfg(blocks: Dict[int, BasicBlock]) -> None:
    """Pretty-print structured CFG ANF blocks."""
    for label in sorted(blocks):
        print(blocks[label])
