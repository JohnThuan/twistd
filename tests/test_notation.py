"""The notation translator is checked against an independent, geometry-only simulator.

The reference rotates every sticker (centers included) in the chosen layers, so
wide moves, slices and rotations are simulated directly rather than rewritten.
The whole cube is then turned so the centers are back home, and the result
must match what the translator's face turns produce.
"""

import random
import re

import pytest

from twistd.cube import _FACE_AXIS, _GEOMETRY, _INDEX, InvalidMoveError, _rotate_cw
from twistd.cube import MOVES as FACE_MOVES
from twistd.methods.notation import invert, move_count, to_face_turns

Vec = tuple[int, int, int]

# token letter -> (axis to turn around, which layers: set of dot(pos, axis) values)
_LAYERS: dict[str, tuple[Vec, set[int]]] = {
    **{f: (_FACE_AXIS[f], {1}) for f in "URFDLB"},
    **{f.lower(): (_FACE_AXIS[f], {0, 1}) for f in "URFDLB"},
    "M": (_FACE_AXIS["L"], {0}),
    "E": (_FACE_AXIS["D"], {0}),
    "S": (_FACE_AXIS["F"], {0}),
    "x": (_FACE_AXIS["R"], {-1, 0, 1}),
    "y": (_FACE_AXIS["U"], {-1, 0, 1}),
    "z": (_FACE_AXIS["F"], {-1, 0, 1}),
}


def _dot(a: Vec, b: Vec) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _perm(letter: str) -> tuple[int, ...]:
    """perm[dest] = src for one clockwise quarter turn of the token's layers."""
    axis, layers = _LAYERS[letter]
    perm = list(range(54))
    for src, (pos, normal) in enumerate(_GEOMETRY):
        if _dot(pos, axis) in layers:
            perm[_INDEX[(_rotate_cw(pos, axis), _rotate_cw(normal, axis))]] = src
    return tuple(perm)


_REF = {letter: _perm(letter) for letter in _LAYERS}
_CENTERS = [9 * i + 4 for i in range(6)]


def _apply(state: list[int], perm: tuple[int, ...]) -> list[int]:
    return [state[src] for src in perm]


def _reference(algorithm: str) -> list[int]:
    state = list(range(54))  # every sticker labelled by its home slot
    for token in algorithm.split():
        letter, wide, suffix = re.fullmatch(r"(\w)(w?)(2|'|)", token).groups()  # type: ignore[union-attr]
        if wide:
            letter = letter.lower()
        for _ in range({"": 1, "'": 3, "2": 2}[suffix]):
            state = _apply(state, _REF[letter])
    # Undo any net rotation: try each of the 24 orientations until the centers are home.
    for rotation in _ORIENTATIONS:
        candidate = _apply(state, rotation)
        if all(candidate[c] == c for c in _CENTERS):
            return candidate
    raise AssertionError("no rotation restores the centers")


def _all_orientations() -> list[tuple[int, ...]]:
    """Closure of x and y: all 24 whole-cube orientations as permutations."""
    identity = tuple(range(54))
    seen = {identity}
    frontier = [identity]
    while frontier:
        nxt = []
        for perm in frontier:
            for r in ("x", "y"):
                composed = tuple(perm[src] for src in _REF[r])
                if composed not in seen:
                    seen.add(composed)
                    nxt.append(composed)
        frontier = nxt
    assert len(seen) == 24
    return list(seen)


_ORIENTATIONS = _all_orientations()


def _translated(algorithm: str) -> list[int]:
    state = list(range(54))
    moves, _ = to_face_turns(algorithm)
    for move in moves:
        state = _apply(state, FACE_MOVES[move])
    return state


@pytest.mark.parametrize(
    "algorithm",
    [
        "R U R' U'",
        "r U R' U R U2 r'",
        "M2 U M U2 M' U M2",
        "x R2 D2 R U R' D2 R U' R x'",
        "Rw U Rw'",
        "f R U R' U' f'",
        "M' U M2 U M2 U M' U2 M2",
        "y R U R' y'",
        "S R S'",
        "E2 u d' l b",
        "x y z x' y2 z' R",
    ],
)
def test_translation_matches_geometric_simulation(algorithm: str) -> None:
    assert _translated(algorithm) == _reference(algorithm)


def test_random_mixed_notation_matches_geometric_simulation() -> None:
    rng = random.Random(0)
    tokens = [*"URFDLBurfdlbMESxyz"]
    for _ in range(200):
        alg = " ".join(rng.choice(tokens) + rng.choice(["", "'", "2"]) for _ in range(12))
        assert _translated(alg) == _reference(alg), alg


def test_rotations_cancel_to_identity_frame() -> None:
    _, frame = to_face_turns("r U R' U R U2 r'")
    assert all(user == real for user, real in frame.items())


def test_invert_and_move_count() -> None:
    assert invert("R U2 r' x") == "x' r U2 R'"
    assert move_count("x R U R' y") == 3


def test_unknown_notation_rejected() -> None:
    with pytest.raises(InvalidMoveError):
        to_face_turns("R Q")
    with pytest.raises(InvalidMoveError):
        to_face_turns("Mw")
