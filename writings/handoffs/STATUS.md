# bytecode-anf Status

**Author**: Carter Schonwald  
**Created**: 2026-03-16T21:00:00-04:00  
**Updated**: 2026-03-22T11:48:00-04:00  
**Python**: 3.10–3.14 (tested on 3.14.3)  
**Version**: 0.4.0

## Changelog
- 2026-03-16T21:00-04:00: Initial status doc
- 2026-03-16T21:30-04:00: v0.4.0 release notes
- 2026-03-22T11:48-04:00: Moved to writings/handoffs/

---

## What This Is

Recovers ANF (A-Normal Form) from Python bytecode using:
- Danvy's stack ↔ CPS ↔ ANF isomorphism (mechanical transform)
- Cousot & Cousot abstract interpretation (annotation flow via lattices)

See README.md for usage, DESIGN.md for architecture.

## What Changed (v0.4.0, March 2026)

### Python 3.13/3.14 Opcode Support

Added ~30 new opcodes to both `stack_to_anf.py` (ANF conversion)
and `builtin_transfers.py` (abstract interpretation):

- **Superinstructions** (3.13): `LOAD_FAST_LOAD_FAST`,
  `STORE_FAST_STORE_FAST`, `STORE_FAST_LOAD_FAST`
- **Borrowed refs** (3.14): `LOAD_FAST_BORROW`,
  `LOAD_FAST_BORROW_LOAD_FAST_BORROW`
- **Small int optimization** (3.14): `LOAD_SMALL_INT`
- **F-string opcodes** (3.13): `FORMAT_SIMPLE`, `FORMAT_WITH_SPEC`,
  `CONVERT_VALUE`
- **Template strings** (3.14, PEP 750): `BUILD_TEMPLATE`,
  `BUILD_INTERPOLATION`
- **Control flow**: `TO_BOOL`, `NOT_TAKEN`, `POP_ITER`, `CALL_KW`
- Plus: `SET_FUNCTION_ATTRIBUTE`, `LOAD_COMMON_CONSTANT`,
  `LOAD_SPECIAL`, `LOAD_LOCALS`, `DELETE_*`, `STORE_DEREF`,
  `UNPACK_EX`, `BINARY_SLICE`, `STORE_SLICE`, and more

See `opcode_versions.py` for the full provenance map (opcode → version
introduced/removed).

### IR Type Cleanup

- `ANFBinding` replaces `Tuple[ANFVar, ANFExpr]` everywhere
- `ANFBody` replaces `List[Tuple[...]]` + terminator
- `KWArg` replaces `Optional[dict]` for keyword args
- `ANFPhi` **removed**, replaced by `ANFJoin` (codata join points)
- All frozen dataclasses with proper `__repr__`

### Codata Join Points

`ANFPhi` (SSA-style, variable-major) replaced by `ANFJoin` (codata,
path-major). See `JOIN_POINTS.md` for the full design rationale.

Key idea: join points are coinductive records (additive &) where each
field is a predecessor path with its own type signature and body. All
fields share the enclosing closure. Jumps are method calls.

Theoretical foundation: Carter Schonwald, "Linearity, Dependency, and
Simultaneity" (2026), the n-ary additive & connective from the Π–Σ
type former.

## Current Sharp Spots

### Resolved
- ✅ Type lattice precision (v3: proper subtype DAG with LCA-based join)
- ✅ BINARY_OP consolidation (op argument decoded)
- ✅ Pattern matching opcodes (MATCH_*)
- ✅ Intrinsic calls (CALL_INTRINSIC_1/2)
- ✅ Python version drift (3.10–3.14, provenance tracked)
- ✅ Phi nodes → codata join points (ANFJoin designed, AST defined)

### Partially Done
- 🟡 **Exception handling**: opcodes handled, CFG edges missing
  (need exception table parsing from `code.co_exceptiontable`)
- 🟡 **Generators/coroutines**: yield/return_generator handled,
  suspension model incomplete
- 🟡 **Comprehensions**: LIST_APPEND/SET_ADD/MAP_ADD handled,
  recursive descent into nested code objects missing
- 🟡 **Stack depth validation**: passive check exists, could assert+warn
- 🟡 **ANFJoin wiring**: AST nodes defined, not yet emitted by
  StackToANF or used by AbstractInterpreter

### Not Started
- ⬜ CFG-aware ANF output using ANFJoin at merge points
- ⬜ Exception table → CFG edges (3.11+)
- ⬜ Recursive transform of nested code objects
- ⬜ Generator suspension model (yield as suspend/resume edges)
- ⬜ Source mapping (bytecode offset → source line)
- ⬜ Migrate `stack_to_anf.py` internals to `ANFBinding`/`ANFBody`
- ⬜ Convert `ANFPrim.args`/`ANFCall.args` from `List` to `tuple`

## Module Map

| Module | Lines | Role |
|--------|-------|------|
| `anf.py` | 251 | AST nodes (ANFVar, ANFPrim, ANFCall, ANFBinding, ANFBody, ANFJoin, ...) |
| `stack_to_anf.py` | 912 | Bytecode → ANF transform + CFG builder |
| `builtin_transfers.py` | 608 | Transfer functions for ~100 opcodes (TypeLattice) |
| `builtin_lattices.py` | 241 | TypeLattice with subtype DAG |
| `interpreter.py` | 228 | Abstract interpreter (linear scan + CFG worklist) |
| `lattice.py` | 191 | AnnotationLattice ABC, AnnotatedValue, AbstractStack |
| `transfer.py` | 137 | TransferRegistry + @annotates DSL |
| `opcode_versions.py` | 249 | Opcode → version provenance map |

## Test Coverage

66 tests, all passing on Python 3.14.3. Covers:
- ANF node construction and repr
- Stack-to-ANF conversion (basic, nested, locals, calls)
- CFG building (linear, branching, loops)
- Type lattice (join, meet, leq, from_value; full subtype DAG)
- Abstract stack (push/pop/join)
- Transfer function registration (exact, family, precedence, isolation)
- Abstract interpretation (type propagation, trace recording, CFG fixpoint)
- Join point construction
- Unpack ordering (version-aware: UNPACK_SEQUENCE vs STORE_FAST_STORE_FAST)
- End-to-end: mixed numeric propagation, bool promotion, loop termination

## Key Design Decisions

1. **Codata join points, not SSA phi**: see JOIN_POINTS.md
2. **Scoped TransferRegistry**: avoid cross-analysis contamination
3. **Subtype DAG for TypeLattice**: LCA-based join, not flat top
4. **Per-opcode version provenance**: opcode_versions.py
5. **Named types over anonymous tuples**: ANFBinding, ANFBody, etc.
