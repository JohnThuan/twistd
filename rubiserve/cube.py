"""Facelet-level cube model: input validation, move application, scrambling.

Facelet strings use the kociemba layout: faces in U R F D L B order, 9 stickers
each, each face read row by row as seen from outside the cube in the standard net

        U
    L   F   R   B
        D

Move permutations are derived from 3D geometry rather than hand-typed tables:
every sticker gets a (cubie position, outward normal) pair, and a face turn is a
90-degree rotation of the stickers in that layer.
"""

from __future__ import annotations

import random
from typing import Final

FACES: Final = "URFDLB"
SOLVED: Final = "".join(face * 9 for face in FACES)
CENTER_INDICES: Final = tuple(9 * i + 4 for i in range(6))

Vec = tuple[int, int, int]


class InvalidCubeError(ValueError):
    """Base class for any cube input the service rejects with a 400."""


class MalformedCubeError(InvalidCubeError):
    """The facelet string is not structurally valid."""


class UnsolvableCubeError(InvalidCubeError):
    """The facelet string is well-formed but not a reachable cube state."""


class InvalidMoveError(ValueError):
    """A move sequence contains an unknown token."""


def normalize(cube: str) -> str:
    return cube.strip().upper()


def validate_facelets(cube: str) -> None:
    """Structural checks. Deeper solvability (twist/flip/parity) is left to the solver."""
    if len(cube) != 54:
        raise MalformedCubeError(f"cube must be exactly 54 characters, got {len(cube)}")

    bad = sorted(set(cube) - set(FACES))
    if bad:
        raise MalformedCubeError(
            f"invalid facelet characters {bad}; allowed characters are {list(FACES)}"
        )

    for face in FACES:
        count = cube.count(face)
        if count != 9:
            raise MalformedCubeError(f"face '{face}' must appear exactly 9 times, got {count}")

    centers = "".join(cube[i] for i in CENTER_INDICES)
    if centers != FACES:
        raise MalformedCubeError(
            f"center stickers must be '{FACES}' (positions {list(CENTER_INDICES)}), got '{centers}'"
        )


def is_solved(cube: str) -> bool:
    return cube == SOLVED


# --- geometry --------------------------------------------------------------
# Axes: x -> R, y -> U, z -> F.

_FACE_AXIS: Final[dict[str, Vec]] = {
    "U": (0, 1, 0),
    "R": (1, 0, 0),
    "F": (0, 0, 1),
    "D": (0, -1, 0),
    "L": (-1, 0, 0),
    "B": (0, 0, -1),
}


def _sticker_position(face: str, r: int, c: int) -> Vec:
    match face:
        case "U":
            return (c - 1, 1, r - 1)
        case "R":
            return (1, 1 - r, 1 - c)
        case "F":
            return (c - 1, 1 - r, 1)
        case "D":
            return (c - 1, -1, 1 - r)
        case "L":
            return (-1, 1 - r, c - 1)
        case "B":
            return (1 - c, 1 - r, -1)
    raise AssertionError(face)


def _dot(a: Vec, b: Vec) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _rotate_cw(v: Vec, axis: Vec) -> Vec:
    """Rotate v by -90 degrees about a unit axis (clockwise when viewed from +axis)."""
    cx = _cross(axis, v)
    d = _dot(axis, v)
    return (-cx[0] + axis[0] * d, -cx[1] + axis[1] * d, -cx[2] + axis[2] * d)


_GEOMETRY: Final = tuple(
    (_sticker_position(face, i // 3, i % 3), _FACE_AXIS[face]) for face in FACES for i in range(9)
)
_INDEX: Final = {geom: idx for idx, geom in enumerate(_GEOMETRY)}

Perm = tuple[int, ...]


def _quarter_turn(face: str) -> Perm:
    """perm[dest] = src: the sticker at src moves to dest."""
    axis = _FACE_AXIS[face]
    perm = list(range(54))
    for src, (pos, normal) in enumerate(_GEOMETRY):
        if _dot(pos, axis) == 1:
            perm[_INDEX[(_rotate_cw(pos, axis), _rotate_cw(normal, axis))]] = src
    return tuple(perm)


def _permute(state: str, perm: Perm) -> str:
    return "".join(state[src] for src in perm)


def _compose(first: Perm, second: Perm) -> Perm:
    return tuple(first[src] for src in second)


def _build_moves() -> dict[str, Perm]:
    moves: dict[str, Perm] = {}
    for face in FACES:
        q = _quarter_turn(face)
        half = _compose(q, q)
        moves[face] = q
        moves[face + "2"] = half
        moves[face + "'"] = _compose(half, q)
    return moves


MOVES: Final = _build_moves()


def parse_moves(sequence: str) -> list[str]:
    tokens = sequence.split()
    unknown = [t for t in tokens if t not in MOVES]
    if unknown:
        raise InvalidMoveError(f"unknown moves: {unknown}")
    return tokens


def apply_moves(state: str, sequence: str) -> str:
    for move in parse_moves(sequence):
        state = _permute(state, MOVES[move])
    return state


def invert_moves(sequence: str) -> str:
    inverted = []
    for move in reversed(parse_moves(sequence)):
        if move.endswith("2"):
            inverted.append(move)
        elif move.endswith("'"):
            inverted.append(move[0])
        else:
            inverted.append(move + "'")
    return " ".join(inverted)


def random_scramble(length: int = 25, rng: random.Random | None = None) -> str:
    """Random move sequence that never turns the same face twice in a row."""
    rng = rng or random.Random()
    moves: list[str] = []
    last_face = ""
    for _ in range(length):
        face = rng.choice([f for f in FACES if f != last_face])
        moves.append(face + rng.choice(("", "'", "2")))
        last_face = face
    return " ".join(moves)
