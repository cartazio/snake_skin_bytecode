# bytecode-anf Design Document

**Author**: Carter Schonwald  
**Version**: 1.0  
**Target**: Python 3.11+, degrades gracefully to 3.10

---

## Theoretical Foundation

### Danvy's Correspondence

The core insight is from Olivier Danvy's work on defunctionalization and the CPS/direct-style correspondence:

```
Stack machine ⟷ CPS ⟷ ANF
```

A stack machine's evaluation state *is* a continuation. Each stack position corresponds to a let-bound variable in ANF:

| Stack Operation | ANF Equivalent |
|-----------------|----------------|
| `PUSH v`        | `let $n = v in ...` |
| `POP` (use)     | Reference to `$n` |
| Binary op       | `let $m = $a op $b` (consumes 2, produces 1) |

This isn't an analogy. It's structural isomorphism. The transform is:
1. Name each stack position at each instruction
2. Each PUSH creates a binding
3. Each POP references a binding
4. Result: ANF falls out mechanically

### Cousot & Cousot's Abstract Interpretation

The annotation layer follows the standard abstract interpretation framework:

1. **Lattice**: Abstract domain with ⊔ (join), ⊓ (meet), ⊑ (ordering), ⊥ (bottom), ⊤ (top)
2. **Transfer functions**: Per-opcode semantics in the abstract domain
3. **Fixpoint**: Iterate until convergence at CFG join points

For finite-height lattices, termination is guaranteed.

---

## Architecture

```
           ┌─────────────────────────────────────────────┐
           │              Python bytecode                │
           │            (dis.Bytecode(code))             │
           └─────────────────┬───────────────────────────┘
                             │
                             ▼
           ┌─────────────────────────────────────────────┐
           │               CFGBuilder                    │
           │  • Find basic block leaders                 │
           │  • Compute predecessor/successor edges      │
           │  • Handle: jumps, branches, returns         │
           └─────────────────┬───────────────────────────┘
                             │
                             ▼
           ┌─────────────────────────────────────────────┐
           │               StackToANF                    │
           │  • Simulate stack per basic block           │
           │  • Emit let-bindings for each push          │
           │  • Track locals map (STORE_FAST → var)      │
           └─────────────────┬───────────────────────────┘
                             │
                             ▼
           ┌─────────────────────────────────────────────┐
           │           AbstractInterpreter               │
           │  • Run transfer functions per opcode        │
           │  • Propagate annotations through stack      │
           │  • Join at CFG merge points                 │
           └─────────────────┬───────────────────────────┘
                             │
                             ▼
              ANF AST + Annotations per binding
```

### Key Components

| Module | Responsibility |
|--------|----------------|
| `anf.py` | ANF AST node definitions |
| `stack_to_anf.py` | Bytecode → ANF transform (Danvy) |
| `lattice.py` | Abstract domain base class |
| `transfer.py` | `@annotates` decorator DSL |
| `interpreter.py` | Abstract interpretation driver |
| `builtin_lattices.py` | Example: TypeLattice |
| `builtin_transfers.py` | Transfer functions for ~60 opcodes |

---

## Sharp Spots

### 1. Stack State at Join Points

**Problem**: When control flow merges (after if/else, loop entry), stack contents may be symbolically different even if depth matches.

```python
if cond:
    x = 1      # stack: [$1 = 1]
else:
    x = foo()  # stack: [$2 = call(foo)]
# merge here: what's on stack?
```

**Current handling**: `AbstractStack.join_with()` creates phi-nodes:
```python
φ($1, $2)  # annotation = join(ann($1), ann($2))
```

**Sharp edge**: The ANF output doesn't currently emit explicit phi-nodes in the AST. The interpreter handles it, but the raw `StackToANF` output doesn't track cross-block joins.

**Fix**: Add `ANFPhi` node, compute it during CFG-aware transform (not just linear scan).

---

### 2. Exception Handling

**Problem**: `try`/`except`/`finally` creates implicit control flow edges. Exception handlers receive the exception on stack.

**Current handling**: Not explicitly modeled. The opcodes exist (`SETUP_FINALLY` in 3.10, exception table in 3.11+), but we don't build exception edges in CFG.

**Sharp edge**: Stack state at exception handler entry isn't tracked. Missing: `PUSH_EXC_INFO`, `POP_EXCEPT`, `RERAISE`, `CHECK_EXC_MATCH`.

**Fix**: 
1. Parse the exception table (3.11+: `code.co_exceptiontable`)
2. Add edges from protected range → handler
3. Model exception stack frame (type, value, traceback)

---

### 3. Generators and Coroutines

**Problem**: `yield`/`yield from`/`await` reify continuations. The generator protocol is CPS made explicit.

**Current handling**: `YIELD_VALUE`, `GET_YIELD_FROM_ITER`, `SEND` are present but modeled simplistically.

**Sharp edge**: Generator state isn't a stack, it's a suspended continuation. Each yield point is a potential entry point on resume.

**Fix**: Model generator frames as separate CFGs with multiple entry points. Each `YIELD_VALUE` creates an edge to the subsequent instruction *and* a suspend edge. This is genuinely harder than regular control flow.

---

### 4. Comprehensions

**Problem**: List/dict/set comprehensions and generator expressions compile to separate code objects.

```python
[x*2 for x in range(10)]
# Compiles to: MAKE_FUNCTION + CALL, where the function contains the loop
```

**Current handling**: We see `MAKE_FUNCTION` but don't recurse into the nested code object.

**Fix**: Recursively transform `code.co_consts` entries that are code objects. Build a tree of ANF modules.

---

### 5. Pattern Matching (Python 3.10+)

**Problem**: `match`/`case` introduces new opcodes: `MATCH_CLASS`, `MATCH_MAPPING`, `MATCH_SEQUENCE`, `MATCH_KEYS`, `COPY_DICT_WITHOUT_KEYS`.

**Current handling**: Falls through to "unknown opcode" recording.

**Fix**: Add transfer functions. These are structurally similar to unpacking, just need the stack effects:

| Opcode | Stack Effect |
|--------|--------------|
| `MATCH_SEQUENCE` | `[subject] → [bool]` |
| `MATCH_MAPPING` | `[subject] → [bool]` |
| `MATCH_CLASS` | `[subject, *patterns] → [bool or tuple]` |

---

### 6. Intrinsic Calls (Python 3.12+)

**Problem**: Python 3.12 added `CALL_INTRINSIC_1` and `CALL_INTRINSIC_2` for builtin operations that don't go through normal call machinery.

**Current handling**: Not handled.

**Fix**: Intrinsic IDs are enumerated in `_opcode_metadata.py`. Add transfer functions per intrinsic.

---

### 7. Python Version Drift

**Problem**: Bytecode changes significantly between Python versions. Opcodes are added, removed, renamed, renumbered.

| Version | Major Changes |
|---------|---------------|
| 3.9 | Last version with `LOAD_METHOD`/`CALL_METHOD` pair |
| 3.10 | Pattern matching, `MATCH_*` opcodes |
| 3.11 | Specializing interpreter, `CACHE` instructions, exception table, `PUSH_NULL`+`CALL` replaces old call machinery |
| 3.12 | `LOAD_FAST_AND_CLEAR`, `CALL_INTRINSIC_*`, `LOAD_SUPER_ATTR`, more specialization |

**Current handling**: Targets 3.11+ primarily. Some 3.10 compatibility.

**Fix**: Version-specific opcode tables. Could use `sys.version_info` to select appropriate handlers. Or: accept `dis.Bytecode` abstracts over raw bytes, so handle what `dis` exposes.

---

### 8. BINARY_OP Consolidation (3.11+)

**Problem**: Python 3.11 merged all binary operations into `BINARY_OP` with a numeric argument encoding the operation. Earlier versions had separate opcodes (`BINARY_ADD`, `BINARY_SUBTRACT`, etc.).

**Current handling**: Both paths are handled, but `BINARY_OP` doesn't decode the op argument to provide precise semantics.

**Fix**: Decode `instr.argrepr` or use the operation table from `dis`:

```python
# Operation codes (from Python source)
BINARY_OP_NAMES = {
    0: '+', 1: '&', 2: '//', 3: '<<', 4: '@', 5: '*',
    6: '%', 7: '|', 8: '**', 9: '>>', 10: '-', 11: '/',
    12: '^', 13: '+=', 14: '&=', # ... etc
}
```

---

### 9. Stack Depth Validation

**Problem**: `code.co_stacksize` gives the maximum stack depth, but we don't validate our simulation against it.

**Current handling**: We trust our simulation.

**Fix**: Assert `len(self.stack) <= code.co_stacksize` periodically. Mismatches indicate bugs in transfer functions.

---

### 10. Type Lattice Precision

**Problem**: The example `TypeLattice` is deliberately simple. `join(num, int) = ⊤` is wrong (should be `num`).

**Current handling**: Known imprecision for demo purposes.

**Fix**: Proper subtype lattice:

```
        ⊤
       /|\
      / | \
   num str bool  ...
   /\       |
  /  \      |
int float   |
  \   |    /
   \  |   /
     ⊥
```

---

## Completeness Argument

### Claim: ∀ valid Python bytecode B, ANF recovery terminates.

**Proof sketch**:

1. **Finite instruction set**: `len(dis.opmap) = 140` (3.12). Each opcode has computable stack effect.

2. **Bounded stack**: `code.co_stacksize` is computed at compile time. Stack depth never exceeds this.

3. **Finite CFG**: Number of basic blocks ≤ number of instructions. Each instruction belongs to exactly one block.

4. **Local transform**: Each instruction transforms stack[i] → stack[i'] in O(1).

5. **Composition**: CFG traversal is O(|instructions|). Per-instruction transform is O(1). Total: O(n).

**For annotation flow with fixpoint**:

6. **Lattice height**: If lattice has finite height h, fixpoint converges in O(h × |blocks|) iterations.

7. **Widening**: For infinite-height lattices (e.g., intervals), widening guarantees termination.

∴ The transform is total and computable. QED.

---

## What's Complete vs. What's Missing

### Complete (handles all cases)

- Basic blocks and linear code
- Binary/unary operators
- Local variable load/store
- Function calls (CALL, CALL_FUNCTION variants)
- Collection construction (list, tuple, dict, set)
- Attribute access
- Subscript operations
- Simple control flow (if/else, loops, return)
- Stack manipulation (DUP, ROT, COPY, SWAP)
- Imports
- Basic closure handling

### Partial (handles common cases)

- Exception handling (opcodes present, CFG edges missing)
- Generators (yield modeled, suspension not)
- Context managers (WITH_EXCEPT_START etc. need work)
- Pattern matching (opcodes need transfer functions)

### Missing (needs implementation)

- Recursive transform of nested code objects
- Exception table parsing (3.11+)
- Full generator/coroutine CFG model
- Intrinsic calls (3.12+)
- LOAD_SUPER_ATTR (3.12+)
- Async/await (structurally similar to generators)
- Type stubs integration for precise function return types

---

## Usage

### Basic ANF Recovery

```python
from bytecode_anf import bytecode_to_anf, print_anf

def example(x, y):
    return (x + y) * 2

bindings = bytecode_to_anf(example.__code__)
print_anf(bindings)
# let $g1 = (global 'print')
# let $b2 = (x + y)
# let $b3 = ($b2 * 2)
# let $return = $b3
```

### With Type Annotations

```python
from bytecode_anf import (
    AbstractInterpreter, TypeLattice,
    annotates, clear_transfers
)
from bytecode_anf.builtin_transfers import register_builtin_transfers

# Setup
lattice = TypeLattice()
register_builtin_transfers(lattice)

# Analyze
interp = AbstractInterpreter(lattice)
trace, locals_ann = interp.analyze(
    example.__code__,
    initial_locals={'x': TypeLattice.INT, 'y': TypeLattice.INT}
)

# trace contains (opcode, stack_state) pairs
# locals_ann contains final type for each local
```

### Custom Lattice

```python
from bytecode_anf import AnnotationLattice, annotates

class TaintLattice(AnnotationLattice):
    CLEAN = "clean"
    TAINTED = "tainted"
    
    def bottom(self): return self.CLEAN
    def top(self): return self.TAINTED
    def join(self, a, b): 
        return self.TAINTED if self.TAINTED in (a, b) else self.CLEAN
    def meet(self, a, b):
        return self.CLEAN if self.CLEAN in (a, b) else self.TAINTED
    def leq(self, a, b):
        return a == self.CLEAN or b == self.TAINTED

# Register custom transfer
@annotates('LOAD_FAST')
def taint_load(stack, instr, **ctx):
    name = instr.argval
    ann = TaintLattice.TAINTED if name.startswith('user_') else TaintLattice.CLEAN
    stack.push(AnnotatedValue(name, ann))
```

---

## Future Work

1. **CFG-aware ANF output**: Currently linear scan. Should output per-block bindings with explicit edges and phi-nodes.

2. **Exception edges**: Parse exception table, add handler edges to CFG.

3. **Generator CFG**: Model yield points as suspend/resume edges.

4. **Nested code objects**: Recursive transform for comprehensions, nested functions.

5. **Source mapping**: Track bytecode offset → source line for error messages.

6. **Incremental update**: When source changes, recompute only affected blocks.

7. **Integration with type checkers**: Import type stubs for stdlib to refine call return types.

---

## References

- Danvy, O. (1996). *Type-directed partial evaluation*
- Danvy, O. & Nielsen, L.R. (2003). *Defunctionalization at Work*
- Cousot, P. & Cousot, R. (1977). *Abstract Interpretation: A Unified Lattice Model*
- Python `dis` module documentation
- CPython `compile.c` for bytecode semantics
