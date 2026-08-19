# pyright: strict
"""Join points are live when a consumer executes them equivalently to Python."""

from bytecode_anf import bytecode_to_anf_cfg, execute_anf_cfg


def test_branch_join_executes_both_predecessor_fields() -> None:
    def branch_assign(condition: bool, left: int, right: int) -> int:
        if condition:
            selected = left
        else:
            selected = right
        return selected + 1

    blocks = bytecode_to_anf_cfg(branch_assign.__code__)

    for condition, left, right in ((True, 10, 20), (False, 10, 20)):
        arguments = {"condition": condition, "left": left, "right": right}
        expected = branch_assign(condition, left, right)
        assert execute_anf_cfg(blocks, arguments) == expected


def test_recursive_loop_join_matches_python() -> None:
    def sum_range(count: int) -> int:
        total = 0
        for item in range(count):
            total += item
        return total

    blocks = bytecode_to_anf_cfg(sum_range.__code__)

    for count in (0, 1, 2, 5, 17):
        assert execute_anf_cfg(blocks, {"count": count}) == sum_range(count)
