"""OLL and PLL: the last two CFOP stages, solved by recognizing a known case.

OLL (Orient Last Layer) turns the whole top face one color: 57 cases.
PLL (Permute Last Layer) moves the top pieces into place: 21 cases.

Recognition tables are *generated from the algorithms themselves*: running an
algorithm backwards from a solved cube produces exactly the state it solves.
Doing that for each of the 4 U-turn setups (and 4 finishing U-turns for PLL)
covers every orientation of every case, and the tests check that all 216 OLL
states and all 288 PLL states are covered with nothing left over.

Algorithms and names follow the SpeedSolving wiki's OLL and PLL pages, with
setup turns removed (recognition handles those).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Final

from twistd.cube import SOLVED, apply_moves
from twistd.methods.notation import invert, to_face_turns

# (number, name, algorithm)
OLL: Final = (
    (1, "Runway", "R U2 R2 F R F' U2 R' F R F'"),
    (2, "Zamboni", "F R U R' U' F' f R U R' U' f'"),
    (3, "Anti-Mouse", "f R U R' U' f' U' F R U R' U' F'"),
    (4, "Mouse", "f R U R' U' f' U F R U R' U' F'"),
    (5, "Lefty Square", "l' U2 L U L' U l"),
    (6, "Righty Square", "r U2 R' U' R U' r'"),
    (7, "Lightning", "r U R' U R U2 r'"),
    (8, "Reverse Lightning", "l' U' L U' L' U2 l"),
    (9, "Kite", "R U R' U' R' F R2 U R' U' F'"),
    (10, "Anti-Kite", "R U R' U R' F R F' R U2 R'"),
    (11, "Downstairs", "r' R2 U R' U R U2 R' U M'"),
    (12, "Upstairs", "r R2 U' R U' R' U2 R U' r' R"),
    (13, "Gun", "F U R U2 R' U' R U R' F'"),
    (14, "Anti-Gun", "R' F R U R' F' R F U' F'"),
    (15, "Squeegee", "l' U' l L' U' L U l' U l"),
    (16, "Anti-Squeegee", "r U r' R U R' U' r U' r'"),
    (17, "Slash", "R U R' U R' F R F' U2 R' F R F'"),
    (18, "Crown", "R U2 R2 F R F' U2 M' U R U' r'"),
    (19, "Bunny", "S' R U R' S U' R' F R F'"),
    (20, "Checkers", "r U R' U' M2 U R U' R' U' M'"),
    (21, "Double Sune", "R U R' U R U' R' U R U2 R'"),
    (22, "Pi", "R U2 R2 U' R2 U' R2 U2 R"),
    (23, "Headlights", "R2 D' R U2 R' D R U2 R"),
    (24, "Chameleon", "r U R' U' r' F R F'"),
    (25, "Bowtie", "F R' F' r U R U' r'"),
    (26, "Antisune", "R U2 R' U' R U' R'"),
    (27, "Sune", "R U R' U R U2 R'"),
    (28, "Arrow", "r U R' U' r' R U R U' R'"),
    (29, "Spotted Chameleon", "R U R' U' R U' R' F' U' F R U R'"),
    (30, "Anti-Spotted Chameleon", "F U R U2 R' U' R U2 R' U' F'"),
    (31, "Couch", "R' U' F U R U' R' F' R"),
    (32, "Anti-Couch", "S R U R' U' R' F R f'"),
    (33, "Key", "R U R' U' R' F R F'"),
    (34, "City", "R U R2 U' R' F R U R U' F'"),
    (35, "Fish Salad", "R U2 R2 F R F' R U2 R'"),
    (36, "Wario", "L' U' L U' L' U L U L F' L' F"),
    (37, "Mounted Fish", "F R' F' R U R U' R'"),
    (38, "Mario", "R U R' U R U' R' U' R' F R F'"),
    (39, "Fung", "L F' L' U' L U F U' L'"),
    (40, "Anti-Fung", "R' F R U R' U' F' U R"),
    (41, "Awkward Fish", "R U R' U R U2 R' F R U R' U' F'"),
    (42, "Lefty Awkward Fish", "R' U' R U' R' U2 R F R U R' U' F'"),
    (43, "Anti-P", "R' U' F' U F R"),
    (44, "P", "F U R U' R' F'"),
    (45, "T", "F R U R' U' F'"),
    (46, "Seein' Headlights", "R' U' R' F R F' U R"),
    (47, "Right Front Squeezy", "F R' F' R U2 R U' R' U R U2 R'"),
    (48, "Breakneck", "F R U R' U' R U R' U' F'"),
    (49, "Right Back Squeezy", "r U' r2 U r2 U r2 U' r"),
    (50, "Left Front Squeezy", "R' F R2 B' R2 F' R2 B R'"),
    (51, "Bottlecap", "F U R U' R' U R U' R' F'"),
    (52, "Rice Cooker", "R U R' U R U' B U' B' R'"),
    (53, "Frying Pan", "l' U' L U' L' U L U' L' U2 l"),
    (54, "Anti-Frying Pan", "r U R' U R U' R' U R U2 r'"),
    (55, "Highway", "R' F R U R U' R2 F' R2 U' R' U R U R'"),
    (56, "Streetlights", "r U r' U R U' R' U R U' R' r U' r'"),
    (57, "Mummy", "R U R' U' M' U R U' r'"),
)

# (name, algorithm)
PLL: Final = (
    ("H", "M2 U M2 U2 M2 U M2"),
    ("Ua", "R U' R U R U R U' R' U' R2"),
    ("Ub", "R2 U R U R' U' R' U' R' U R'"),
    ("Z", "M' U M2 U M2 U M' U2 M2"),
    ("Aa", "x R' U R' D2 R U' R' D2 R2 x'"),
    ("Ab", "x R2 D2 R U R' D2 R U' R x'"),
    ("E", "x' R U' R' D R U R' D' R U R' D R U' R' D' x"),
    ("F", "R' U' F' R U R' U' R' F R2 U' R' U' R U R' U R"),
    ("Ga", "R2 U R' U R' U' R U' R2 D U' R' U R D'"),
    ("Gb", "R' U' R U D' R2 U R' U R U' R U' R2 D"),
    ("Gc", "R2 U' R U' R U R' U R2 D' U R U' R' D"),
    ("Gd", "R U R' U' D R2 U' R U' R' U R' U R2 D'"),
    ("Ja", "x R2 F R F' R U2 r' U r U2 x'"),
    ("Jb", "R U R' F' R U R' U' R' F R2 U' R'"),
    ("Na", "R U R' U R U R' F' R U R' U' R' F R2 U' R' U2 R U' R'"),
    ("Nb", "R' U R U' R' F' U' F R U R' F R' F' R U' R"),
    ("Ra", "R U' R' U' R U R D R' U' R D' R' U2 R'"),
    ("Rb", "R2 F R U R U' R' F' R U2 R' U2 R"),
    ("T", "R U R' U' R' F R2 U' R' U' R U R' F'"),
    ("V", "R U' R U R' D R D' R U' D R2 U R2 D' R2"),
    ("Y", "F R U' R' U' R U R' F' R U R' U' R' F R F'"),
)

AUFS: Final = ("", "U", "U'", "U2")

# Sticker slots in the top layer: the U face, then the top row of each side face.
U_FACE: Final = tuple(range(9))
U_SIDES: Final = (9, 10, 11, 18, 19, 20, 36, 37, 38, 45, 46, 47)


@dataclass(frozen=True)
class Case:
    kind: str  # "OLL" or "PLL"
    label: str  # "OLL 27 (Sune)", "T-perm"
    setup: str  # U turn to do first ("" if none)
    algorithm: str  # in cubing notation, as a cuber would read it
    finish: str = ""  # U turn to do last (PLL only)

    @property
    def moves(self) -> str:
        return " ".join(part for part in (self.setup, self.algorithm, self.finish) if part)


def _face_turns(algorithm: str) -> str:
    return " ".join(to_face_turns(algorithm)[0])


def _oll_key(cube: str) -> tuple[bool, ...]:
    """Which top-layer stickers show the top color. That alone decides the OLL case."""
    return tuple(cube[i] == "U" for i in U_FACE + U_SIDES)


def _pll_key(cube: str) -> str:
    """Colors around the top layer's sides. With the top face done, this decides the PLL case."""
    return "".join(cube[i] for i in U_SIDES)


@cache
def oll_table() -> dict[tuple[bool, ...], Case]:
    table: dict[tuple[bool, ...], Case] = {_oll_key(SOLVED): Case("OLL", "OLL skip", "", "")}
    for number, name, alg in OLL:
        turns = _face_turns(alg)
        for setup in AUFS:
            # The state this solves = run (setup, alg) backwards from solved.
            state = apply_moves(SOLVED, invert(f"{setup} {turns}".strip()))
            key = _oll_key(state)
            if key not in table:
                table[key] = Case("OLL", f"OLL {number} ({name})", setup, alg)
    return table


@cache
def pll_table() -> dict[str, Case]:
    table: dict[str, Case] = {}
    # Plain U turns first, so "just turn the top" wins over any algorithm.
    for finish in AUFS:
        state = apply_moves(SOLVED, invert(finish)) if finish else SOLVED
        table.setdefault(_pll_key(state), Case("PLL", "AUF", "", "", finish))
    for name, alg in PLL:
        turns = _face_turns(alg)
        for setup in AUFS:
            for finish in AUFS:
                sequence = " ".join(p for p in (setup, turns, finish) if p)
                key = _pll_key(apply_moves(SOLVED, invert(sequence)))
                table.setdefault(key, Case("PLL", f"{name}-perm", setup, alg, finish))
    return table


def recognize_oll(cube: str) -> Case:
    try:
        return oll_table()[_oll_key(cube)]
    except KeyError:
        raise ValueError("top layer does not match any OLL case; is F2L solved?") from None


def recognize_pll(cube: str) -> Case:
    try:
        return pll_table()[_pll_key(cube)]
    except KeyError:
        raise ValueError("top layer does not match any PLL case; is OLL done?") from None


def apply_case(cube: str, case: Case) -> str:
    return apply_moves(cube, _face_turns(case.moves)) if case.moves else cube
