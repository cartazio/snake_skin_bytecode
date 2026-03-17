# bytecode-anf

Recover ANF-style AST from Python bytecode with annotation flow.

## Foundation

Two classic results:

1. **Danvy's Defunctionalization**: Stack machines and CPS/ANF are syntactically isomorphic. Stack positions are implicit continuation variables. PUSH = let-binding, POP = variable use.

2. **Cousot & Cousot's Abstract Interpretation**: Compute program properties by executing over abstract domains (lattices) with computable transfer functions.

We simulate the bytecode stack with abstract values, producing ANF while propagating annotations through the lattice.

## Computability

For all Python bytecode B, ANF recovery terminates:

- Finite instruction set: `len(dis.opmap) == 140`
- Computable stack effects: `dis.stack_effect(opcode, arg)` is total
- Bounded stack: `code.co_stacksize`
- Finite CFG: bytecode length bounds node count
- Local transform: each instruction maps stack[i] → stack[i'] deterministically
- Finite-height lattice: fixpoint terminates (or use widening)

Complexity: O(|B|) for straight-line code, O(|B| × lattice_height) for loops.

## Install

```bash
pip install bytecode-anf
```

From source:
```bash
git clone https://github.com/cartazio/bytecode-anf
cd bytecode-anf
pip install -e .
```

## Usage

### Basic ANF Recovery

```python
from bytecode_anf import StackToANF, print_anf

def example(x, y):
    z = x + y
    return z * 2

converter = StackToANF(example.__code__)
bindings, _ = converter.process()
print_anf(bindings)
# let $b1 = (+ x y)
# let z = $b1
# let $b2 = (* z 2)
# let $return = $b2
```

### Abstract Interpretation with Types

```python
from bytecode_anf import AbstractInterpreter, TypeLattice
from bytecode_anf.builtin_transfers import register_builtin_transfers

lattice = TypeLattice()
register_builtin_transfers(lattice)

def typed_example(x: int, y: float):
    z = x + y
    return z * 2

interp = AbstractInterpreter(lattice)
result = interp.analyze(
    typed_example.__code__,
    initial_locals={'x': TypeLattice.INT, 'y': TypeLattice.FLOAT}
)

print(result.locals_ann)  # {'x': int, 'y': float, 'z': num}
print(result.return_ann)  # num
```

### Custom Transfer Functions

```python
from bytecode_anf import annotates, annotates_family, AbstractStack, AnnotatedValue

@annotates('LOAD_CONST')
def my_load_const(stack: AbstractStack, instr, **ctx):
    val = instr.argval
    ann = my_lattice.from_value(val)
    stack.push(AnnotatedValue(val, ann))

@annotates_family('BINARY_')
def my_binary_ops(stack: AbstractStack, instr, **ctx):
    b, a = stack.pop(), stack.pop()
    result_ann = my_lattice.join(a.ann, b.ann)
    stack.push(AnnotatedValue("binop", result_ann))
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
    def join(self, a, b): return TaintLevel(max(a.level, b.level))
    def meet(self, a, b): return TaintLevel(min(a.level, b.level))
    def leq(self, a, b): return a.level <= b.level
```

## API

### ANF Nodes

`ANFVar`, `ANFAtom`, `ANFPrim`, `ANFCall`, `ANFLet`, `ANFBinding`, `ANFBody`, `ANFJoin`, `ANFBranch`, `ANFJump`, `ANFReturn`

### Conversion

`StackToANF`, `CFGBuilder`, `bytecode_to_anf`, `print_anf`

### Abstract Interpretation

`AnnotationLattice`, `AnnotatedValue`, `AbstractStack`, `AbstractInterpreter`

### Transfer DSL

`@annotates`, `@annotates_family`, `TransferRegistry`, `get_transfer`, `clear_transfers`

### Built-in

`TypeLattice`, `SimpleType`

## License

MIT

## References

- Danvy & Nielsen (2003), *Defunctionalization at Work*
- Cousot & Cousot (1977), *Abstract Interpretation: A Unified Lattice Model*
- Python `dis` module
