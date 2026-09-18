import random

import numpy as np
import pytest

from twistd.cube import SOLVED, apply_moves, random_scramble
from twistd.methods import cfop
from twistd.methods.pieces import STICKERS, home, locate, move_positions
from twistd.methods.search import table_for

F2L_PIECES = (*cfop.CROSS, *(p for pair in cfop.SLOTS.values() for p in pair))


def _scrambles(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [apply_moves(SOLVED, random_scramble(25, rng)) for _ in range(n)]


def _solved(cube: str, pieces: tuple[str, ...]) -> bool:
    return all(locate(cube, p) == home(p) for p in pieces)


def test_piece_tracking_matches_facelet_moves() -> None:
    rng = random.Random(0)
    for _ in range(50):
        scramble = random_scramble(20, rng)
        positions = tuple(home(p) for p in STICKERS)
        for move in scramble.split():
            positions = move_positions(positions, move)
        cube = apply_moves(SOLVED, scramble)
        assert positions == tuple(locate(cube, p) for p in STICKERS)


def test_cross_table_matches_known_cube_facts() -> None:
    # 12*10*8*6 slot choices * 2^4 flips = 190,080 cross states; none needs more than 8 moves.
    table = table_for(cfop.CROSS).table
    reachable = table[table < 255]
    assert reachable.size == 190_080
    assert reachable.max() == 8
    assert np.count_nonzero(reachable == 8) == 102


@pytest.mark.parametrize("cube", _scrambles(10, seed=1))
def test_cross_is_optimal_and_solves_the_cross(cube: str) -> None:
    step = cfop.solve_cross(cube)
    assert step.move_count == table_for(cfop.CROSS).distance([locate(cube, p) for p in cfop.CROSS])
    assert _solved(apply_moves(cube, " ".join(step.moves)), cfop.CROSS)


@pytest.mark.parametrize("cube", _scrambles(5, seed=2))
def test_f2l_solves_first_two_layers(cube: str) -> None:
    cross = cfop.solve_cross(cube)
    steps = cfop.solve_f2l(cube, cross.moves, ("FR", "FL", "BR", "BL"))
    state = apply_moves(cube, " ".join(cross.moves))
    solved_so_far = cfop.CROSS
    for step, slot in zip(steps, ("FR", "FL", "BR", "BL"), strict=True):
        state = apply_moves(state, " ".join(step.moves))
        solved_so_far = (*solved_so_far, *cfop.SLOTS[slot])
        assert _solved(state, solved_so_far), f"{step.stage} broke something"


@pytest.mark.parametrize("cube", _scrambles(4, seed=3))
def test_best_f2l_is_never_worse_than_a_fixed_order(cube: str) -> None:
    cross = cfop.solve_cross(cube)
    fixed = sum(s.move_count for s in cfop.solve_f2l(cube, cross.moves, ("FR", "FL", "BR", "BL")))
    best = cfop.best_f2l(cube, cross.moves)
    assert sum(s.move_count for s in best) <= fixed
    after = apply_moves(cube, " ".join(cross.moves + sum((s.moves for s in best), ())))
    assert _solved(after, F2L_PIECES)
    assert sorted(s.case for s in best) == sorted(f"{slot} slot" for slot in cfop.SLOTS)


def test_already_solved_cube_needs_no_moves() -> None:
    cross = cfop.solve_cross(SOLVED)
    assert cross.moves == ()
    assert all(s.moves == () for s in cfop.solve_f2l(SOLVED, (), tuple(cfop.SLOTS)))


@pytest.mark.parametrize("best", [False, True], ids=["standard", "best-f2l"])
def test_full_cfop_solves_the_cube(best: bool) -> None:
    from twistd.methods.notation import to_face_turns

    for cube in _scrambles(3, seed=4):
        steps = cfop.solve(cube, best=best)
        assert [s.stage for s in steps] == ["Cross", "F2L 1", "F2L 2", "F2L 3", "F2L 4", "OLL", "PLL"]
        alg = " ".join(" ".join(s.moves) for s in steps)
        assert apply_moves(cube, " ".join(to_face_turns(alg)[0])) == SOLVED
        assert steps[5].case and steps[5].case.startswith("OLL")


def test_human_cfop_uses_only_friendly_moves_and_solves() -> None:
    from twistd.methods.notation import to_face_turns

    for cube in _scrambles(6, seed=5):
        steps = cfop.solve_human(cube)
        alg = " ".join(" ".join(s.moves) for s in steps)
        # The emitted notation, rotations included, must solve the cube as written.
        assert apply_moves(cube, " ".join(to_face_turns(alg)[0])) == SOLVED
        for step in steps[1:5]:
            for move in step.moves:
                assert move[0] in "URLFy", f"{step.stage} uses {move}"


def test_view_after_y_matches_notation() -> None:
    from twistd.methods.notation import to_face_turns
    from twistd.methods.pieces import view_after_y

    cube = apply_moves(SOLVED, "R U F D' L2")
    for turns in range(4):
        fixed = " ".join(to_face_turns("y " * turns + "R U")[0])
        assert view_after_y(apply_moves(cube, fixed), turns) == apply_moves(view_after_y(cube, turns), "R U")
