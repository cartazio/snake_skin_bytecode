# AD as Duality: Structural Rules and the Adjoint Program

**Author**: Carter Schonwald  
**Created**: 2026-03-16  
**Updated**: 2026-03-17

## Changelog
- 2026-03-16: Initial theory notes
- 2026-03-17: Heading cleanup (Semantics, Consequence, Implementation)

---

## The Misleading "Tape" Metaphor

The AD literature's "tape" is implementation-brained nonsense from the 1970s. It describes data structure (linear recording) rather than semantics.

Semantics:

| "Tape" term | Actual structure |
|-------------|------------------|
| Recording | The program's let-bindings already exist |
| Playback | Composing adjoints in reverse binding order |
| Tape entries | ANF bindings (the program itself) |

With ANF, there's no runtime recording. The binding structure is static. Reverse-mode AD reverses the let-nesting:

```
Primal:   let x₁ = f₁(...) in let x₂ = f₂(x₁, ...) in ... in xₙ
Adjoint:  let dx_{n-1} = f'ₙ(dxₙ) in ... in let dx₀ = f'₁(dx₁)
```

---

## The Dual Program

```
Primal:   splits → compute → merges
Dual:     merges → compute† → splits
```

At each **merge** (join point) in the primal:
- Multiple predecessor paths contribute values
- Join computes observation / receives from k paths

At the **same point** in the dual:
- One gradient arrives
- Must **split** back to each predecessor

```
Primal (forward):          Dual (backward):

    B0    B1                  B0    B1
     \   /                     ↑     ↑
      \ /                       \   /
       ↓                         \ /
    merge (j)               split (dj)
       ↓                         ↑
      ...                       ...
```

**Merge† = split. Split† = merge.**

---

## Structural Rules: n-ary Dup and Drop

The structural rules of linear logic govern how values are used:

- **Contraction (dup)**: use a value more than once
- **Weakening (drop)**: use a value zero times

In the dual:

```
Primal                          Dual
──────                          ────
n-ary dup (contraction)    →    n-ary merge (Σ gradients)
n-ary drop (weakening)     →    zero (no contribution)
```

### dup† = merge

Value used n times in primal (n-ary contraction):

```
       x ────┬──→ use₁
             ├──→ use₂
             └──→ use₃
```

Dual: gradients accumulate:

```
       dx ←── d(use₁) + d(use₂) + d(use₃)
```

The "gradient accumulation" that AD systems implement is the adjoint of contraction. Nothing more.

### drop† = 0

Value not used → zero gradient. No forward path, no backward contribution.

---

## Two Faces of Duality

| Structural rule | Primal | Dual |
|-----------------|--------|------|
| **Contraction** (dup) | fan-out to n uses | fan-in (Σ) from n adjoints |
| **Weakening** (drop) | discard | zero contribution |
| **Additive &** (join) | receive from k paths | dispatch to k paths |
| **Additive ⊕** (case) | dispatch to k paths | receive from k paths |

The n-ary dup/drop are the **multiplicative** face.
The join/split are the **additive** face.
Same duality, different connectives.

---

## Connection to Π–Σ Type Former

From "Linearity, Dependency, and Simultaneity" (Schonwald 2026):

The n-ary additive & connective from the Π–Σ type former gives the join point semantics:
- Fields share enclosing closure (the & property)
- Each field has its own type signature
- Jumps are method calls, not tag dispatch

The adjoint of & is ⊕. Join points in the primal become split points in the dual. The codata structure makes this manifest: each field's body gets its own adjoint, and the dual dispatches gradients based on which field was invoked.

---

## Consequence

"Tape" hides structure. The actual picture:

**AD is the dagger (†) functor on the program's linear structure.**

- The adjoint reverses arrows
- dup↔merge falls out from contraction†
- drop↔zero falls out from weakening†
- join↔split falls out from &†

The codata join points in bytecode-anf make the additive structure explicit. The ANF bindings make the multiplicative structure (which values flow where) explicit. Together: the complete information needed to mechanically derive the adjoint program.

No tape. No recording. Just the program and its dual.

---

## Implementation

Given ANF with codata join points:

1. **Binding reversal**: Walk bindings in reverse order
2. **Primitive adjoints**: Each primitive op has a known VJP
3. **Dup sites**: Where a variable is used n>1 times, accumulate n adjoint contributions
4. **Drop sites**: Variables used 0 times contribute nothing
5. **Join points**: The dual dispatches gradients back along each predecessor path

The adjoint program can be derived mechanically from the ANF + usage analysis. No runtime "recording"; the structure is the program.
