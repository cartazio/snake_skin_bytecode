# Join Points: Codata Replaces Phi

**Author**: Carter Schonwald  
**Created**: 2026-03-16  
**Updated**: 2026-03-16

## Changelog
- 2026-03-16: Initial design rationale
- 2026-03-16: Tightened prose

---

## The Problem

When control flow merges (after if/else, loop headers), the IR must
reconcile values from different predecessors. SSA's answer is phi nodes.
We use something better.

## Why Not Phi

SSA phi nodes are **variable-major**: one φ per variable that differs
across predecessors.

```
B0: x₀ = 1; y₀ = 2
B1: x₁ = 3; y₁ = 4
Merge:
  x = φ(B0:x₀, B1:x₁)
  y = φ(B0:y₀, B1:y₁)
  ... use x, y ...
```

Problems:
- First-order: selects by label, no compositional structure
- Variable-major decomposition is unnatural; the predecessors are the
  meaningful units, not the individual variables
- No type signature per path
- No linearity story
- Doesn't compose (can't cut on one phi)

## The Replacement: Codata Join Points

A join point is a **corecord** (codata) in the sense of Agda coinductives.
It has one **method** (field) per predecessor path. All methods share the
enclosing closure. This is the additive **&** (with) connective from linear
logic: same context, multiple observations, only one demanded.

```
-- Shared closure: everything bound before the branch
let a = ...
let b = ...

join j over {a, b} =
  | .from_B0(x : int, y : int) → body₀(a, b, x, y)
  | .from_B1(x : str, y : int) → body₁(a, b, x, y)

if cond then j.from_B0(1, 2)
         else j.from_B1("hi", 4)
```

### Key Properties

**Path-major, not variable-major.** One method per predecessor. Each
method carries ALL its bindings as parameters. The decomposition unit
is the path, not the variable.

**Each method has its own type signature.** B0 might provide
`{x:int, y:int}`, B1 might provide `{x:str, y:int}`. Types are
per-path, not per-variable-across-paths.

**Each method has its own body.** Often shared in practice (that's the
point of merging), but structurally they're independent case arms.
When shared, the body sees the lattice join of per-method type
signatures.

**Shared closure = additive &.** All methods close over the same
pre-branch bindings. This is the defining property of the additive
connective: context is shared, not split. Multiplicative ⊗ would split
the context between branches; that's wrong for join points.

**Jumps are method calls.** A predecessor doesn't "jump to merge with
label B0"; it calls `j.from_B0(values...)`. Dispatch is structural
(which method was invoked), not first-order (match on a tag).

**Composable via cut.** Join points are methods. Composition is function
composition. You can cut on one path's output without disturbing the
others: exactly the cut rule of linear sequent calculus applied to the
Π–Σ type former.

### The Transposition

Phi is NxM (N variables × M predecessors), indexed variable-first.
Join is MxN (M methods × N params each), indexed path-first.

Same information, but the path-first decomposition:
- groups related bindings together (a path's values are a unit)
- attaches type signatures where they belong (per path)
- makes the jump-as-method-call pattern structural
- lets each path have its own continuation

### Connection to Known Constructions

| Tradition | What it calls this |
|-----------|--------------------|
| Agda | Coinductive record, copattern matching |
| GHC Core | Join point (SPJ, "Compiling without continuations") |
| Linear logic | Additive & (with), n-ary |
| OO (immutable) | Object with methods sharing frozen state |
| CBPV | Negative type (defined by elimination) |
| Π–Σ (Schonwald 2026) | `Π(tag : Path) → Σ{bindings(tag)}` with & semantics |

### In the AST

```python
@dataclass
class ANFJoin:
    """Codata join point: additive & over shared closure."""
    name: ANFVar
    fields: List[JoinField]     # one per predecessor path

@dataclass
class JoinField:
    """One method/observation of the join corecord."""
    label: int                  # predecessor block offset
    params: List[JoinParam]     # this path's bindings
    body: ANFBody               # this path's continuation

@dataclass
class JoinParam:
    """A parameter of a join field: binding with optional type."""
    var: ANFVar
    ann: Any = None             # type from abstract interpretation
```

The shared closure is implicit: it's the lexical scope enclosing the
ANFJoin, same as how & shares Γ implicitly in the sequent calculus.

## How It Replaces Phi In Practice

Given bytecode for:
```python
if cond:
    x = 1
    y = "a"
else:
    x = 2
    y = "b"
z = x + y
```

**Old (phi):**
```
B0: let x₀ = 1; let y₀ = "a"
B1: let x₁ = 2; let y₁ = "b"
Merge:
  x = φ(B0:x₀, B1:x₁)
  y = φ(B0:y₀, B1:y₁)
  z = x + y
```

**New (codata join):**
```
join j =
  | .from_B0(x : int, y : str) →
      let z = x + y
      return z
  | .from_B1(x : int, y : str) →
      let z = x + y
      return z

B0: let x = 1; let y = "a"; j.from_B0(x, y)
B1: let x = 2; let y = "b"; j.from_B1(x, y)
```

Bodies happen to be identical here; a smart IR pass can share them.
But the representation doesn't force sharing; it falls out when
appropriate.

## References

- Carter Schonwald, "Linearity, Dependency, and Simultaneity: A Unified
  Π–Σ Type Former for Linear Logic" (2026), §4.4 (additive &),
  Remark 3.1 (coinductive flavor of linear elimination)
- SPJ et al., "Compiling without continuations" (2017), join points in GHC
- Abel et al., "Copatterns: Programming Infinite Structures by
  Observations" (2013), codata in Agda
- Zeilberger, "The Logical Basis of Evaluation Order and
  Pattern-Matching" (2009), polarity and focusing
