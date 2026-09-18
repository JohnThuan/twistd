import random

import pytest

from twistd.cube import SOLVED, apply_moves
from twistd.methods import last_layer as ll
from twistd.methods.cfop import CROSS, SLOTS
from twistd.methods.notation import to_face_turns
from twistd.methods.pieces import home, locate

F2L_PIECES = (*CROSS, *(p for pair in SLOTS.values() for p in pair))


def _turns(alg: str) -> str:
    return " ".join(to_face_turns(alg)[0])


def _f2l_intact(cube: str) -> bool:
    return all(locate(cube, p) == home(p) for p in F2L_PIECES)


def _random_last_layer(rng: random.Random, generators: list[str], steps: int = 25) -> str:
    """A random top-layer state reached only by moves that never touch the first two layers."""
    cube = SOLVED
    for _ in range(steps):
        cube = apply_moves(cube, _turns(rng.choice(generators)))
    return cube


@pytest.mark.parametrize(("number", "name", "alg"), ll.OLL, ids=[f"OLL{n}" for n, _, _ in ll.OLL])
def test_oll_algorithm_keeps_f2l(number: int, name: str, alg: str) -> None:
    assert _f2l_intact(apply_moves(SOLVED, _turns(alg)))


@pytest.mark.parametrize(("name", "alg"), ll.PLL, ids=[n for n, _ in ll.PLL])
def test_pll_algorithm_keeps_f2l_and_top_color(name: str, alg: str) -> None:
    cube = apply_moves(SOLVED, _turns(alg))
    assert _f2l_intact(cube)
    assert all(cube[i] == "U" for i in ll.U_FACE), "a PLL must not change orientation"


def test_every_oll_algorithm_is_a_distinct_case() -> None:
    labels = {case.label for case in ll.oll_table().values()}
    assert len(labels) == 57 + 1  # 57 cases + skip


def test_every_pll_algorithm_is_a_distinct_case() -> None:
    labels = {case.label for case in ll.pll_table().values()}
    assert len(labels) == 21 + 1  # 21 cases + AUF-only


def test_oll_covers_all_216_top_layer_orientations() -> None:
    # Sune twists corners, T-OLL flips edges, U moves them around: together they
    # reach every orientation state, without using the table's own algorithms.
    rng = random.Random(0)
    generators = ["U", "R U R' U R U2 R'", "F R U R' U' F'"]
    seen = {ll._oll_key(_random_last_layer(rng, generators)) for _ in range(20_000)}
    assert len(seen) == 216
    assert seen <= set(ll.oll_table())


def test_pll_covers_all_288_top_layer_permutations() -> None:
    rng = random.Random(1)
    # T-perm swaps *opposite* edges, so with U turns alone it only reaches 48 states;
    # J-perm's *adjacent* edge swap completes the set of every top-layer permutation.
    generators = ["U", "R U R' U' R' F R2 U' R' U' R U R' F'", "R U R' F' R U R' U' R' F R2 U' R'"]
    seen = {ll._pll_key(_random_last_layer(rng, generators)) for _ in range(20_000)}
    assert len(seen) == 288
    assert seen <= set(ll.pll_table())


def test_recognized_cases_actually_solve_their_state() -> None:
    rng = random.Random(2)
    generators = ["U", "R U R' U R U2 R'", "F R U R' U' F'", "R U R' U' R' F R2 U' R' U' R U R' F'"]
    for _ in range(300):
        cube = _random_last_layer(rng, generators)
        oll = ll.recognize_oll(cube)
        oriented = ll.apply_case(cube, oll)
        assert all(oriented[i] == "U" for i in ll.U_FACE), oll.label
        pll = ll.recognize_pll(oriented)
        assert ll.apply_case(oriented, pll) == SOLVED, pll.label


def test_skip_cases() -> None:
    assert ll.recognize_oll(SOLVED).label == "OLL skip"
    assert ll.recognize_pll(SOLVED).moves == ""
