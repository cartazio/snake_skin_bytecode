# bytecode-anf Design Document

**Author**: Carter Schonwald  
**Created**: 2026-03-16  
**Updated**: 2026-03-16  
**Version**: 1.0  
**Target**: Python 3.11+, degrades gracefully to 3.10

## Changelog
- 2026-03-16: Initial design doc
- 2026-03-16: Tightened prose, added tables

---

## Theoretical Foundation

### Danvy's Correspondence

Stack machine ⟷ CPS ⟷ ANF

A stack machine's evaluation state *is* a continuation. Each stack position corresponds to a let-bound variable in ANF:

| Stack Operation | ANF Equivalent |
|-----------------|----------------|
| `PUSH v`        | `let $n = v in ...` |
| `POP` (use)     | Reference to `$n` |
| Binary op       | `let $m = $a op $b` (consumes 2, produces 1) |

Structural isomorphism, not analogy. The transform:
1. Name each stack position at each instruction
2. Each PUSH creates a binding
3. Each POP references a binding
4. ANF falls out mechanically

### Cousot & Cousot's Abstract Interpretation

1. **Lattice**: Abstract domain with ⊔ (join), ⊓ (meet), ⊑ (ordering), ⊥ (bottom), ⊤ (top)
2. **Transfer functions**: Per-opcode semantics in the abstract domain
3. **Fixpoint**: Iterate until convergence at CFG join points

For finite-height lattices, termination is guaranteed.

---

## Architecture

```
Python bytecode (dis.Bytecode)
        ↓
    CFGBuilder         find leaders, compute edges
        ↓
    StackToANF         simulate stack, emit let-bindings
        ↓
AbstractInterpreter    run transfers, propagate annotations
        ↓
ANF AST + Annotations
```

| Module | Role |
|--------|------|
| `anf.py` | AST nodes |
| `stack_to_anf.py` | Bytecode → ANF (Danvy) |
| `lattice.py` | Abstract domain ABC |
| `transfer.py` | `@annotates` DSL |
| `interpreter.py` | Abstract interpretation |
| `builtin_lattices.py` | TypeLattice |
| `builtin_transfers.py` | ~100 opcode transfers |

---

## Sharp Spots

| Area | Status | Gap | Fix |
|------|--------|-----|-----|
| Join points | `AbstractStack.join_with()` creates φ | ANF output lacks explicit φ | CFG-aware transform emits `ANFJoin` |
| Exceptions | Opcodes handled | No CFG edges protected→handler | Parse `code.co_exceptiontable` |
| Generators | `YIELD_VALUE`/`SEND` present | Suspension not modeled | Multi-entry CFG per frame |
| Comprehensions | See `MAKE_FUNCTION` | No recursion into nested code | Transform `code.co_consts` |
| Pattern matching | Falls through | Missing `MATCH_*` transfers | Add transfers |
| Intrinsics (3.12+) | Not handled | `CALL_INTRINSIC_1/2` | Transfer per intrinsic ID |
| Version drift | Targets 3.11+ | 3.9/3.10 gaps | Version tables or trust `dis` |
| `BINARY_OP` | Both paths | Op arg not decoded | Use `instr.argrepr` |
| Stack validation | Trust simulation | No `co_stacksize` check | Assert periodically |
| Type lattice | ✓ Fixed (v0.4) | Subtype DAG done | n/a |

---

## Completeness

**Claim**: ∀ valid Python bytecode B, ANF recovery terminates.

1. Finite instruction set: `len(dis.opmap) = 140`
2. Bounded stack: `code.co_stacksize`
3. Finite CFG: blocks ≤ instructions
4. Local transform: O(1) per instruction
5. Composition: O(n) total

For fixpoint: lattice height h → O(h × |blocks|) iterations. Widening handles infinite lattices.

---

## Coverage

**Done**: basic blocks, operators, locals, calls, collections, attributes, subscripts, control flow, stack ops, imports, closures

**Partial**: exceptions (opcodes yes, edges no), generators (yield yes, suspend no), context managers, pattern matching

**Missing**: nested code recursion, exception table, generator CFG, intrinsics, async/await, type stub integration

---

## Usage

```python
from bytecode_anf import bytecode_to_anf, print_anf

def f(x, y):
    return (x + y) * 2

print_anf(bytecode_to_anf(f.__code__))
# let $b1 = (+ x y)
# let $b2 = (* $b1 2)
# let $return = $b2
```

With types:
```python
from bytecode_anf import AbstractInterpreter, TypeLattice
from bytecode_anf.builtin_transfers import register_builtin_transfers

lattice = TypeLattice()
register_builtin_transfers(lattice)
interp = AbstractInterpreter(lattice)
result = interp.analyze(f.__code__, {'x': TypeLattice.INT, 'y': TypeLattice.INT})
```

---

## References

- Danvy & Nielsen (2003), *Defunctionalization at Work*
- Cousot & Cousot (1977), *Abstract Interpretation*
- Python `dis` module
- CPython `compile.c`
