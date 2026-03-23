# bytecode-anf

Recover ANF-style AST from Python bytecode with annotation flow.

## Scope

1. Turn arbitrary Python bytecode into a genuinely nice compiler IR: state of the art with neat general constructs.

2. A generic, user-extensible bytecode abstract interpreter toolkit.

## Install

```bash
git clone https://github.com/cartazio/snake_skin_bytecode
cd snake_skin_bytecode
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

## Docs

The API and design are still evolving—no stable inter-version API yet.

## License

MIT

## References

- Danvy & Nielsen (2003), *Defunctionalization at Work*
- Cousot & Cousot (1977), *Abstract Interpretation: A Unified Lattice Model*
- Python `dis` module
