import random

import pytest

from twistd.cube import SOLVED, apply_moves, random_scramble
from twistd.methods import beginner
from twistd.methods.notation import to_face_turns

STAGES = [
    "Cross",
    "First layer corners",
    "Middle layer",
    "Yellow cross",
    "Yellow edges",
    "Place yellow corners",
    "Twist yellow corners",
]


def _scrambles(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [apply_moves(SOLVED, random_scramble(25, rng)) for _ in range(n)]


@pytest.mark.parametrize("cube", _scrambles(40, seed=10))
def test_beginner_solution_solves_the_cube_as_written(cube: str) -> None:
    steps = beginner.solve(cube)
    alg = " ".join(" ".join(s.moves) for s in steps)
    assert apply_moves(cube, " ".join(to_face_turns(alg)[0])) == SOLVED


def test_stages_come_in_teaching_order() -> None:
    for cube in _scrambles(10, seed=11):
        seen = [s.stage for s in beginner.solve(cube)]
        order = [STAGES.index(stage) for stage in seen]
        assert order == sorted(order), seen


def test_steps_only_use_the_taught_algorithms() -> None:
    taught = {
        beginner.SEXY,
        beginner.RIGHT_INSERT,
        beginner.RIGHT_INSERT_FROM_SIDE,
        beginner.YELLOW_CROSS,
        beginner.SUNE,
        beginner.CORNER_CYCLE,
        beginner.CORNER_TWIST,
    }
    for cube in _scrambles(10, seed=12):
        for step in beginner.solve(cube):
            if step.stage != "Cross" and step.algorithm is not None:
                assert step.algorithm in taught
                assert step.algorithm in " ".join(step.moves)


def test_solved_cube_needs_no_steps() -> None:
    assert beginner.solve(SOLVED) == []
