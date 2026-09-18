"""Pieces (cubies) as seen by the teaching methods.

The facelet string says what color is on each of the 54 sticker slots. Human
methods think in pieces instead: "the DF edge", "the DFR corner". Each piece is
tracked by one reference sticker (its U/D-colored one if it has one, otherwise
its F/B one). Where that sticker sits pins down the piece's slot *and* its
orientation, so a piece's whole state is one integer in 0..53.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Final

from twistd.cube import _FACE_AXIS, _GEOMETRY, MOVES

# Faces listed first name the piece first ("DF", not "FD") and supply its reference sticker.
_PRIORITY: Final = "UDFBRL"
_AXIS_FACE: Final = {axis: face for face, axis in _FACE_AXIS.items()}


def _piece_name(faces: list[str]) -> str:
    return "".join(sorted(faces, key=_PRIORITY.index))


def _build() -> tuple[dict[str, tuple[int, ...]], dict[int, tuple[int, ...]]]:
    by_position: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    for index, (position, normal) in enumerate(_GEOMETRY):
        by_position[position].append((index, _AXIS_FACE[normal]))

    stickers_of: dict[str, tuple[int, ...]] = {}
    slot_of_sticker: dict[int, tuple[int, ...]] = {}
    for stickers in by_position.values():
        if len(stickers) == 1:
            continue  # centers never move relative to each other
        ordered = sorted(stickers, key=lambda s: _PRIORITY.index(s[1]))
        indices = tuple(i for i, _ in ordered)
        stickers_of[_piece_name([f for _, f in ordered])] = indices
        for i in indices:
            slot_of_sticker[i] = indices
    return stickers_of, slot_of_sticker


# Piece name -> its sticker slots in the solved cube, reference sticker first.
STICKERS: Final = _build()[0]
# Sticker slot -> all sticker slots of the piece position it belongs to.
_SLOT: Final = _build()[1]

EDGES: Final = tuple(name for name in STICKERS if len(name) == 2)
CORNERS: Final = tuple(name for name in STICKERS if len(name) == 3)

# Which slots a reference sticker can ever occupy: edges only visit edge slots, etc.
EDGE_SLOTS: Final = tuple(sorted(i for n in EDGES for i in STICKERS[n]))
CORNER_SLOTS: Final = tuple(sorted(i for n in CORNERS for i in STICKERS[n]))


def _next_positions() -> dict[str, tuple[int, ...]]:
    """NEXT[move][p] = where the sticker now at p ends up after the move."""
    table = {}
    for move, perm in MOVES.items():  # perm[dest] = src
        nxt = [0] * 54
        for dest, src in enumerate(perm):
            nxt[src] = dest
        table[move] = tuple(nxt)
    return table


NEXT: Final = _next_positions()


def home(piece: str) -> int:
    """Reference sticker position when the piece is solved."""
    return STICKERS[piece][0]


def locate(cube: str, piece: str) -> int:
    """Where the piece's reference sticker currently is in a facelet string."""
    colors = set(piece)
    ref_color = piece[0]
    for i in STICKERS[piece][:1] + tuple(EDGE_SLOTS if len(piece) == 2 else CORNER_SLOTS):
        if cube[i] == ref_color and {cube[j] for j in _SLOT[i]} == colors:
            return i
    raise ValueError(f"piece {piece} not found; cube is malformed")


def move_positions(positions: tuple[int, ...], move: str) -> tuple[int, ...]:
    nxt = NEXT[move]
    return tuple(nxt[p] for p in positions)
