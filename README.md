# bytecode-anf

Recover ANF-style AST from Python bytecode with annotation flow.

## Theoretical Foundation

This library operationalizes two classic results:

1. **Danvy's Defunctionalization** (1990s): Stack machines and CPS/ANF are
   syntactically isomorphic. Stack positions are implicit continuation variables.
   Each PUSH creates a let-binding; each POP uses a bound variable.

2. **Cousot & Cousot's Abstract Interpretation** (1977): Compute properties
   of programs by executing them over abstract domains (lattices) with
   computable transfer functions.

The combination: we simulate the bytecode stack with abstract values,
producing ANF while propagating annotations through the lattice.

## Computability Proof Sketch

For all Python bytecode B, ANF recovery with annotation is computable:

1. **Finite instruction set**: `len(dis.opmap) == 140`
2. **Computable stack effects**: `dis.stack_effect(opcode, arg)` is total
3. **Bounded stack depth**: `code.co_stacksize` gives max depth
4. **Finite CFG**: bytecode length bounds node count
5. **Local transformation**: each instruction maps stack[i] → stack[i'] deterministically
6. **Finite-height lattice**: fixpoint terminates (or use widening)

Therefore: transform terminates in O(|B|) for straight-line code,
O(|B| × lattice_height) for loops with widening.

## Installation

```bash
pip install bytecode-anf
```

Or from source:

```bash
git clone https://github.com/cartazio/bytecode-anf
cd bytecode-anf
pip install -e .
```

## Quick Start

### Basic ANF Recovery

```python
from bytecode_anf import StackToANF, print_anf

def example(x, y):
    z = x + y
    return z * 2

converter = StackToANF(example.__code__)
bindings, _ = converter.process()
print_anf(bindings)
# Output:
# let $b1 = (+ x y)
# let z = $b1
# let $b2 = (* z 2)
# let $return = $b2
```

### Abstract Interpretation with Types

```python
from bytecode_anf import (
    AbstractInterpreter, TypeLattice,
    register_defaults, clear_transfers
)

# Set up the type lattice
lattice = TypeLattice()
clear_transfers()  # Clear any existing registrations

# Register built-in transfer functions
from bytecode_anf.builtin_transfers import register_builtin_transfers
register_builtin_transfers(lattice)

# Analyze a function
def typed_example(x: int, y: float):
    z = x + y
    return z * 2

interp = AbstractInterpreter(lattice)
result = interp.analyze(
    typed_example.__code__,
    initial_locals={'x': TypeLattice.INT, 'y': TypeLattice.FLOAT}
)

print("Locals:", result.locals_ann)
# {'x': int, 'y': float, 'z': num}

print("Return type:", result.return_ann)
# num (or ⊤ depending on lattice precision)
```

### Custom Transfer Functions

```python
from bytecode_anf import annotates, annotates_family, AbstractStack

# Define custom transfer for a specific opcode
@annotates('LOAD_CONST')
def my_load_const(stack: AbstractStack, instr, **ctx):
    val = instr.argval
    # Your custom annotation logic here
    ann = my_lattice.from_value(val)
    stack.push(AnnotatedValue(val, ann))

# Define transfer for an opcode family
@annotates_family('BINARY_')
def my_binary_ops(stack: AbstractStack, instr, **ctx):
    b = stack.pop()
    a = stack.pop()
    result_ann = my_lattice.join(a.ann, b.ann)
    stack.push(AnnotatedValue(f"binop", result_ann))
```

### Custom Lattices

```python
from bytecode_anf import AnnotationLattice
from dataclasses import dataclass

@dataclass(frozen=True)
class TaintLevel:
    level: int  # 0 = clean, 1 = tainted, 2 = highly tainted

class TaintLattice(AnnotationLattice[TaintLevel]):
    CLEAN = TaintLevel(0)
    TAINTED = TaintLevel(1)
    HIGHLY_TAINTED = TaintLevel(2)
    
    def bottom(self): return self.CLEAN
    def top(self): return self.HIGHLY_TAINTED
    
    def join(self, a, b):
        return TaintLevel(max(a.level, b.level))
    
    def meet(self, a, b):
        return TaintLevel(min(a.level, b.level))
    
    def leq(self, a, b):
        return a.level <= b.level
```

## API Reference

### ANF AST Nodes

- `ANFVar(name)`: Variable
- `ANFAtom(value)`: Atomic expression (var or constant)
- `ANFPrim(op, args)`: Primitive operation
- `ANFCall(func, args)`: Function call
- `ANFLet(var, rhs, body)`: Let-binding
- `ANFBranch(cond, true_label, false_label)`: Conditional branch
- `ANFJump(label)`: Unconditional jump
- `ANFReturn(value)`: Return

### Conversion

- `StackToANF(code)`: Stack-to-ANF converter
- `CFGBuilder(code)`: Control flow graph builder
- `bytecode_to_anf(code)`: Simple conversion function

### Abstract Interpretation

- `AnnotationLattice[A]`: Abstract base class for lattices
- `AnnotatedValue[A]`: Value with annotation
- `AbstractStack[A]`: Stack of annotated values
- `AbstractInterpreter(lattice)`: Main interpreter

### Transfer Functions

- `@annotates(*opcodes)`: Register for specific opcodes
- `@annotates_family(prefix)`: Register for opcode family
- `get_transfer(opname)`: Get registered transfer function
- `clear_transfers()`: Clear all registrations

### Built-in Lattices

- `TypeLattice`: Simple type inference
- `SimpleType`: Type representation

## License

MIT

## References

- Danvy, O. (1996). "Type-directed partial evaluation"
- Danvy, O. & Nielsen, L.R. (2001). "Defunctionalization at Work"
- Cousot, P. & Cousot, R. (1977). "Abstract Interpretation: A Unified Lattice Model"
- Python `dis` module documentation
