"""Exact distance tables and IDA* search over sets of pieces.

A *distance table* answers "how many moves until these pieces are all solved?"
for every arrangement of a small set of pieces. It is built once by breadth-first
search outward from the solved state (moves are reversible, so distance *from*
solved equals distance *to* solved), vectorized with numpy.

IDA* (iterative-deepening A*) then searches for a stage's solution using the
tables as a lower bound: any branch where `depth + bound > limit` is cut. With an
exact table the search walks straight down; with several partial tables it still
prunes most of the 18^n tree.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence
from functools import cache
from pathlib import Path
from typing import Final

import numpy as np

from twistd.cube import MOVES
from twistd.methods.pieces import CORNER_SLOTS, EDGE_SLOTS, NEXT, home

MOVE_NAMES: Final = tuple(MOVES)
_OPPOSITE: Final = {"U": "D", "D": "U", "R": "L", "L": "R", "F": "B", "B": "F"}
_FACE_ORDER: Final = "URFDLB"
_BASE: Final = 24


def _slot_index(piece: str) -> dict[int, int]:
    slots = EDGE_SLOTS if len(piece) == 2 else CORNER_SLOTS
    return {pos: i for i, pos in enumerate(slots)}


def _slot_positions(piece: str) -> tuple[int, ...]:
    return EDGE_SLOTS if len(piece) == 2 else CORNER_SLOTS


class DistanceTable:
    """Exact moves-to-solved for every arrangement of `pieces` (at most 5)."""

    def __init__(self, pieces: Sequence[str], cache_dir: Path | None = None) -> None:
        if not 1 <= len(pieces) <= 5:
            raise ValueError("tables support 1 to 5 pieces")
        self.pieces = tuple(pieces)
        self._index = [_slot_index(p) for p in self.pieces]
        self._weights = [_BASE**k for k in range(len(self.pieces))]
        self.table = self._load_or_build(cache_dir)
        # Indexing a bytes object is several times faster than a numpy scalar lookup,
        # and the search does millions of them.
        self.raw = self.table.tobytes()

    def _load_or_build(self, cache_dir: Path | None) -> np.ndarray:
        if cache_dir is None:
            return self._build()
        path = cache_dir / f"{'-'.join(self.pieces)}.npy"
        if path.exists():
            return np.load(path)
        table = self._build()
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash or a concurrent worker never sees a half-written file.
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".npy.tmp")
        with os.fdopen(fd, "wb") as f:
            np.save(f, table)
        os.replace(tmp, path)
        return table

    def code(self, positions: Sequence[int]) -> int:
        return sum(ix[p] * w for ix, p, w in zip(self._index, positions, self._weights, strict=True))

    def distance(self, positions: Sequence[int]) -> int:
        return self.raw[self.code(positions)]

    def slot_index(self, k: int) -> dict[int, int]:
        """Position -> slot index for the k-th piece (used to precompute codes)."""
        return self._index[k]

    def _build(self) -> np.ndarray:
        n = len(self.pieces)
        # trans[k][m][i]: slot index of piece k after move m, if it was at slot index i.
        trans = []
        for piece, index in zip(self.pieces, self._index, strict=True):
            slots = _slot_positions(piece)
            trans.append(
                [np.array([index[NEXT[m][pos]] for pos in slots], dtype=np.int64) for m in MOVE_NAMES]
            )

        dist = np.full(_BASE**n, 255, dtype=np.uint8)
        start = self.code([home(p) for p in self.pieces])
        dist[start] = 0
        frontier = np.array([start], dtype=np.int64)
        depth = 0
        while frontier.size:
            digits = [(frontier // w) % _BASE for w in self._weights]
            depth += 1
            for m in range(len(MOVE_NAMES)):
                code = np.zeros_like(frontier)
                for k in range(n):
                    code += trans[k][m][digits[k]] * self._weights[k]
                # Marking in place dedupes for free; no sort of the whole frontier needed.
                code = code[dist[code] == 255]
                dist[code] = depth
            frontier = np.flatnonzero(dist == depth)
        return dist


def table_dir() -> Path:
    return Path(os.getenv("TWISTD_TABLE_DIR", Path.home() / ".cache" / "twistd" / "tables"))


@cache
def table_for(pieces: tuple[str, ...]) -> DistanceTable:
    """Tables are expensive to build and immutable: built once, cached on disk and in memory."""
    return DistanceTable(pieces, cache_dir=table_dir())


def _allowed_after(last: str | None) -> tuple[str, ...]:
    """Skip redundant sequences: same face twice (R R), and opposite faces in both
    orders (U D and D U are the same thing, so only one order is explored)."""
    if last is None:
        return MOVE_NAMES
    face = last[0]
    return tuple(
        m
        for m in MOVE_NAMES
        if m[0] != face
        and not (m[0] == _OPPOSITE[face] and _FACE_ORDER.index(m[0]) < _FACE_ORDER.index(face))
    )


_ALLOWED: Final = {last: _allowed_after(last) for last in (None, *MOVE_NAMES)}

Heuristic = Callable[[tuple[int, ...]], int]


def ida_star(
    start: tuple[int, ...],
    heuristic: Heuristic,
    max_depth: int = 20,
    moves: Sequence[str] | None = None,
) -> list[str] | None:
    """Shortest move sequence taking `start` to a state with heuristic 0.

    `start` holds the reference-sticker positions of every tracked piece; the
    heuristic must be admissible (never overestimate) and 0 exactly at the goal.
    """
    allowed_moves = set(moves) if moves is not None else None
    path: list[str] = []

    def dfs(state: tuple[int, ...], depth: int, limit: int, last: str | None) -> bool:
        h = heuristic(state)
        if h == 0:
            return True
        if depth + h > limit:
            return False
        for m in _ALLOWED[last]:
            if allowed_moves is not None and m not in allowed_moves:
                continue
            nxt = NEXT[m]
            path.append(m)
            if dfs(tuple(nxt[p] for p in state), depth + 1, limit, m):
                return True
            path.pop()
        return False

    for limit in range(heuristic(start), max_depth + 1):
        if dfs(start, 0, limit, None):
            return path
    return None
