"""Full cubing notation -> plain face turns.

Speedcubing algorithms use more than the 18 face turns the solver works in:
wide moves (r, u, f... or Rw), slices (M, E, S) and whole-cube rotations
(x, y, z). Internally the cube keeps its centers fixed, so each of those is
rewritten as face turns plus a change of *frame*: after an `x`, the face the
user calls U is the one that was at F, so a later "U" really turns F.

    r  = L x      (both turn the left layer the same way; r = whole cube minus L)
    M  = R L' x'
"""

from __future__ import annotations

import re
from typing import Final

from twistd.cube import InvalidMoveError

_FACES: Final = "URFDLB"

# After rotating the cube, which original face now sits in each user position.
# x turns like R (F comes up to U), y like U (R comes round to F), z like F (U goes to R).
_ROTATION_STEP: Final = {
    "x": {"U": "F", "F": "D", "D": "B", "B": "U", "R": "R", "L": "L"},
    "y": {"F": "R", "R": "B", "B": "L", "L": "F", "U": "U", "D": "D"},
    "z": {"R": "U", "D": "R", "L": "D", "U": "L", "F": "F", "B": "B"},
}

# Wide and slice moves as (face turns, rotation) with matching quarter-turn direction.
_WIDE: Final = {
    "r": ("L", "x"),
    "l": ("R", "x'"),
    "u": ("D", "y"),
    "d": ("U", "y'"),
    "f": ("B", "z"),
    "b": ("F", "z'"),
    "M": ("R L'", "x'"),
    "E": ("U D'", "y'"),
    "S": ("F' B", "z"),
}

_TOKEN: Final = re.compile(r"^([URFDLBurfdlbMESxyz])(w?)(2|'|2'|)$")

Frame = dict[str, str]


def identity_frame() -> Frame:
    return {f: f for f in _FACES}


def rotate_frame(frame: Frame, axis: str, turns: int) -> Frame:
    """The frame after `turns` quarter rotations about x, y or z."""
    for _ in range(turns % 4):
        step = _ROTATION_STEP[axis]
        frame = {user: frame[step[user]] for user in _FACES}
    return frame


def _turns(suffix: str) -> int:
    return {"": 1, "'": 3, "2": 2, "2'": 2}[suffix]


def _face_turn(face: str, turns: int) -> str:
    return face + {1: "", 2: "2", 3: "'"}[turns % 4]


def _invert_token(token: str) -> str:
    if token.endswith("'"):
        return token[:-1]
    if token.endswith("2"):
        return token
    return token + "'"


def to_face_turns(algorithm: str) -> tuple[list[str], Frame]:
    """Translate an algorithm into fixed-center face turns.

    Returns the face turns plus the final frame (identity if the algorithm's
    rotations cancel out, as they do for r ... r' style algorithms).
    """
    frame = identity_frame()
    out: list[str] = []
    for raw in algorithm.replace("(", " ").replace(")", " ").split():
        match = _TOKEN.match(raw)
        if not match:
            raise InvalidMoveError(f"unknown move: {raw!r}")
        letter, wide, suffix = match.groups()
        turns = _turns(suffix)
        if wide:  # Rw is the same as r
            if letter not in _FACES:
                raise InvalidMoveError(f"unknown move: {raw!r}")
            letter = letter.lower()

        if letter in "xyz":
            frame = rotate_frame(frame, letter, turns)
        elif letter in _FACES:
            out.append(_face_turn(frame[letter], turns))
        else:
            base_moves, rotation = _WIDE[letter]
            for _ in range(turns):
                for move in base_moves.split():
                    out.append(_face_turn(frame[move[0]], _turns(move[1:])))
                frame = rotate_frame(frame, rotation[0], _turns(rotation[1:]))
    return _simplify(out), frame


def _simplify(moves: list[str]) -> list[str]:
    """Merge consecutive turns of the same face (R R -> R2, R R' -> nothing)."""
    stack: list[tuple[str, int]] = []
    for move in moves:
        face, turns = move[0], _turns(move[1:])
        if stack and stack[-1][0] == face:
            total = (stack.pop()[1] + turns) % 4
            if total:
                stack.append((face, total))
        else:
            stack.append((face, turns))
    return [_face_turn(face, turns) for face, turns in stack]


def invert(algorithm: str) -> str:
    """Inverse in the algorithm's own notation (works for rotations and wide moves too)."""
    return " ".join(_invert_token(t) for t in reversed(algorithm.split()))


def move_count(algorithm: str) -> int:
    """Moves as a cuber counts them (HTM): rotations are free, everything else is 1."""
    return sum(1 for t in algorithm.split() if t[0] not in "xyz")
