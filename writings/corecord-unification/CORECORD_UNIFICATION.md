# Corecord Unification: ANFJoin as Universal Construction

**Author**: Carter Schonwald  
**Created**: 2026-03-22  
**Status**: Design sketch

## Changelog
- 2026-03-22: Initial sketch

---

## Observation

`ANFJoin` is not specific to control flow merge points. It is the
universal construction for everything the IR *builds* — any entity
defined by its observations (methods/fields) over a shared closure.

Join points, generators, objects, iterators, and context managers
are the same codata construction with different **usage disciplines**.

## The Corecord

A corecord (coinductive record) is:
- A set of named **fields** (observations/methods)
- A **shared closure** (the enclosing scope, the & property)
- Each field has its own **type signature** and **body**

```
corecord C over {shared_env} =
  | .field₁(params₁) → body₁
  | .field₂(params₂) → body₂
  | ...
```

Elimination is observation: `c.field_k(args)` selects and invokes one
field. Construction is copattern matching: define each field's behavior.

## Usage Disciplines

The same corecord structure admits different usage disciplines:

| Discipline | Meaning | Enforcement |
|-----------|---------|-------------|
| **Linear** | Each field called at most once, exactly one chosen | Compiler (control flow) |
| **Sequential** | Fields called in order (entry, resume₁, resume₂, ...) | Runtime (generator protocol) |
| **Protocol** | Fields called in specified order (__enter__ before __exit__) | Convention / types |
| **Unrestricted** | Any field, any order, any number of times | None (general objects) |

### Control Flow Join Points (Linear)

At a CFG merge, exactly one predecessor path is taken. The corecord
is used once, immediately, internally.

```
join j over {a, b} =
  | .from_B0(x : int, y : int) → body(a, b, x, y)
  | .from_B1(x : str, y : int) → body(a, b, x, y)

if cond then j.from_B0(1, 2)
         else j.from_B1("hi", 4)
```

### Generators (Sequential)

Each yield point defines a field. The generator object is a reified
corecord. `next(gen)` = `g.resume_k(None)`. `gen.send(val)` = `g.resume_k(val)`.

```
corecord gen over {frame_locals} =
  | .entry(args)      → body₀ ... yield v₁ → suspend as .resume₁
  | .resume₁(sent₁)   → body₁ ... yield v₂ → suspend as .resume₂
  | .resume₂(sent₂)   → body₂ ... return final
```

No "multi-entry CFG" needed. Single entry per field; the corecord
threads state between observations. `RETURN_GENERATOR` marks the
construction as reified; `YIELD_VALUE` emits a field boundary.

### Objects (Unrestricted)

Every Python object with methods is a corecord:

```
corecord obj over {self.__dict__} =
  | .method_a(args) → body_a
  | .method_b(args) → body_b
  | .__getattr__(name) → ...
```

`__dict__` is the shared closure. Method calls are field observations.
This is exactly what "everything is an object" means read through
the codata lens.

### Iterators (Protocol: Sequential Subset)

```
corecord it over {state} =
  | .__iter__() → self
  | .__next__() → next_value | raise StopIteration
```

### Context Managers (Protocol: Ordered)

```
corecord cm over {resource} =
  | .__enter__() → resource
  | .__exit__(exc_type, exc_val, tb) → suppress?
```

## Two-Layer Architecture

The IR has two kinds of entities:

| Layer | What | Node | Visibility |
|-------|------|------|-----------|
| **Constructed** | Things the IR builds: functions, generators, classes, join points | Corecord (ANFJoin) | Structurally transparent — fields are known |
| **Received** | Things the IR receives: literals, external objects | PyObjRef | Opaque — passed around, not decomposed |

These are complementary. The corecord is the construction principle;
PyObjRef is the embedding principle. A `def` in the analyzed source
produces a corecord. An `int(42)` in the analyzed source produces
a PyObjRef.

The PyObjRef/PyDatum cleanup (giving proper closed types to embeddable
literals) is orthogonal to the corecord unification.

## Formal Connections

| Tradition | Name for This | Key Paper |
|-----------|--------------|-----------|
| Linear logic | Additive & (with), n-ary | Girard (1987) |
| CBPV | Negative type (defined by elimination) | Levy (2004) |
| Agda | Coinductive record, copattern matching | Abel, Pientka, Thibodeau & Setzer (2013) |
| Agda OO | Server-side interactive programs (ΠΣ) | Abel, Adelsberger & Setzer (2016) |
| GHC Core | Join points | SPJ et al. (2017) |
| Π–Σ | `Π(tag:Path) → Σ{bindings(tag)}` with & | Schonwald (2026) |
| Zeilberger | Negative polarity, focusing | Zeilberger (2009) |

The ooAgda paper (Abel, Adelsberger & Setzer 2016) develops exactly
this idea — objects as server-side interactive programs via copatterns
— but in the context of dependently-typed *programming*. 15 citations
in 10 years (Semantic Scholar, March 2026); the insight did not
propagate. In particular, it never reached compiler IR design. We
apply it to a bytecode IR for Python — the first time (to our
knowledge) that the codata/copattern = object equivalence is used
as an IR construction principle rather than a programming technique.

## AD Duality

The corecord makes the additive structure explicit. Under the dagger
functor (†), additive & dualizes to additive ⊕:

| Primal | Dual |
|--------|------|
| Corecord (& — observe one field) | Case/dispatch (⊕ — inject into one branch) |
| Join point: receive from k paths | Split point: dispatch gradient to k paths |
| Generator yield: suspend with value | Generator adjoint: demand gradient at yield |
| Object method: observe/call | Object adjoint: inject gradient for method |

Combined with the multiplicative structure (dup† = Σ gradients,
drop† = zero) from `AD_AS_DUALITY.md`, this gives complete
mechanical AD derivation from ANF + corecord structure.

## Termination

### Code Object Traversal

Code objects form a finite DAG via `co_consts`. Inner functions,
classes, comprehensions, generators all appear as code objects in
their enclosing function's `co_consts` tuple. Inner code objects
do not reference their parent. Recursive descent is structural
recursion on a strict substructure — terminates trivially.

### Abstract Interpretation

Bounded by: finite-height lattice × finite CFG. Each block is
visited at most `lattice_height` times before fixpoint.
O(|blocks| × h). Widening handles infinite-height lattices.

### The Static Visibility Boundary

The IR can see inside a code object iff it appears in the static
`co_consts` DAG rooted at the top-level code object. This is the
boundary between the corecord layer (transparent) and the PyObjRef
layer (opaque):

| Reachable how | Terminates by | Layer |
|---------------|---------------|-------|
| `co_consts` code objects | Structural recursion on finite DAG | Corecord |
| Closure vars (`co_freevars`) | Finite, named statically | Corecord (shared closure) |
| Locals at each point | Fixpoint on finite lattice | Abstract interpretation |
| `eval()`, dynamic `type()`, metaclasses | Not statically reachable | PyObjRef (opaque) |
| Imported modules | Static but potentially huge | Policy: scope boundary |

Dynamically constructed code objects (eval, exec, dynamic type())
are not in the DAG. They remain opaque. This is not a limitation
— it is the correct boundary where structural recursion stops being
available.

### Variable Reachability per Frame

Each code object has finite `co_varnames`, `co_freevars`,
`co_cellvars`. The abstract interpreter tracks annotations for
exactly these. No unbounded variable discovery.

## IR Implications

### Naming

`ANFJoin` should be understood as the linear-usage specialization
of the general corecord. Options:
1. Keep `ANFJoin` for CFG merge points, add `ANFCorecord` as parent
2. Rename `ANFJoin` → `ANFCorecord`, tag with usage discipline
3. Keep `ANFJoin` but document it as the universal construction

Option 3 is cheapest for now; option 2 is cleanest long-term.

### Generator Wiring

`RETURN_GENERATOR` → mark function body as producing a corecord value.
`YIELD_VALUE` → field boundary within the corecord.
`SEND` / `next()` → field observation on the reified corecord.

Falls out mechanically from the existing `ANFJoin` node + `JoinField`
structure. No new AST nodes needed.

### Nested Code Objects

`MAKE_FUNCTION` produces a corecord (the function is callable,
which is a single-field corecord: `.call(args) → body`). For classes,
the class body produces a multi-field corecord (one field per method).

Recursive descent into nested `code` objects instantiates corecords
for inner functions, generators, comprehensions.

## References

- Abel, Pientka, Thibodeau & Setzer (2013). "Copatterns: Programming
  Infinite Structures by Observations." POPL.
- Abel, Adelsberger & Setzer (2016). "Interactive Programming in Agda
  — Objects and Graphical User Interfaces." JFP.
- Girard (1987). "Linear Logic." TCS.
- Levy (2004). *Call-By-Push-Value.* Springer.
- Peyton Jones et al. (2017). "Compiling without continuations." ICFP.
- Schonwald (2026). "Linearity, Dependency, and Simultaneity."
- Zeilberger (2009). "The Logical Basis of Evaluation Order and
  Pattern-Matching." CMU PhD thesis.
