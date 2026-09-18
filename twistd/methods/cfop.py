"""CFOP (Cross, F2L, OLL, PLL): the method most speedcubers use.

The cross goes on the D face. F2L solves the four corner+edge pairs that fill
the first two layers, each without disturbing anything already solved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Final

from twistd.cube import SOLVED, apply_moves
from twistd.methods.last_layer import Case, apply_case, recognize_oll, recognize_pll
from twistd.methods.pieces import NEXT, home, locate
from twistd.methods.search import ida_star, table_for

CROSS: Final = ("DF", "DR", "DB", "DL")
# F2L slot name -> (corner, edge)
SLOTS: Final = {
    "FR": ("DFR", "FR"),
    "FL": ("DFL", "FL"),
    "BR": ("DBR", "BR"),
    "BL": ("DBL", "BL"),
}
F2L_PIECES: Final = (*CROSS, *(piece for pair in SLOTS.values() for piece in pair))


@dataclass(frozen=True)
class Step:
    stage: str
    moves: tuple[str, ...]
    explanation: str
    case: str | None = None

    @property
    def move_count(self) -> int:
        return len(self.moves)


def _slot_tables(slot: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    corner, edge = SLOTS[slot]
    return (*CROSS, corner), (*CROSS, edge)


def warmup() -> None:
    table_for(CROSS)
    for slot in SLOTS:
        for pieces in _slot_tables(slot):
            table_for(pieces)


def solve_cross(cube: str) -> Step:
    """Optimal cross (at most 8 moves), read straight off the exact distance table."""
    table = table_for(CROSS)
    start = tuple(locate(cube, p) for p in CROSS)
    moves = ida_star(start, table.distance, max_depth=8)
    assert moves is not None  # every cross is solvable within 8
    return Step("Cross", tuple(moves), "Solve the four D-layer edges so they match their centers.")


def _f2l_heuristic(solved_slots: tuple[str, ...], target: str) -> Callable[[tuple[int, ...]], int]:
    """Lower bound = the max over "cross + one piece" tables for every pair involved.

    Each table is exact for its 5 pieces, so it never overestimates the full
    stage; taking the max keeps that guarantee and gives the tightest bound.
    """
    cross_table = table_for(CROSS)
    c0, c1, c2, c3 = (cross_table.slot_index(k) for k in range(4))
    fifth = 24**4
    # Every "cross + X" table encodes the cross identically, so the cross part of the
    # code is computed once per node; each table then adds only its fifth piece.
    lookups = []
    for i, slot in enumerate((*solved_slots, target)):
        for j, pieces in enumerate(_slot_tables(slot)):
            table = table_for(pieces)
            index = {pos: ix * fifth for pos, ix in table.slot_index(4).items()}
            lookups.append((table.raw, index, 4 + 2 * i + j))

    def h(state: tuple[int, ...]) -> int:
        base = c0[state[0]] + c1[state[1]] * 24 + c2[state[2]] * 576 + c3[state[3]] * 13824
        best = 0
        for raw, index, at in lookups:
            d = raw[base + index[state[at]]]
            if d > best:
                best = d
        return best

    return h


@cache
def _heuristic_for(solved_slots: tuple[str, ...], target: str) -> Callable[[tuple[int, ...]], int]:
    return _f2l_heuristic(solved_slots, target)


def solve_pair(
    positions: tuple[int, ...], solved_slots: tuple[str, ...], target: str, max_depth: int = 14
) -> list[str] | None:
    """Shortest sequence that solves `target` while keeping the cross and `solved_slots`.

    `positions` = cross edges, then (corner, edge) for each solved slot, then the target pair.
    Returns None if nothing is found within `max_depth` moves.
    """
    return ida_star(positions, _heuristic_for(solved_slots, target), max_depth=max_depth)


def _apply(positions: tuple[int, ...], moves: list[str]) -> tuple[int, ...]:
    for m in moves:
        nxt = NEXT[m]
        positions = tuple(nxt[p] for p in positions)
    return positions


def solve_f2l(cube: str, cross_moves: tuple[str, ...], order: tuple[str, ...]) -> list[Step]:
    """Solve the four pairs in the given slot order, each optimally given the ones before."""
    cross_state = _apply(tuple(locate(cube, p) for p in CROSS), list(cross_moves))
    pair_state = {
        slot: _apply(tuple(locate(cube, p) for p in SLOTS[slot]), list(cross_moves)) for slot in order
    }

    steps: list[Step] = []
    solved: tuple[str, ...] = ()
    for slot in order:
        state = cross_state + sum((pair_state[s] for s in solved), ()) + pair_state[slot]
        moves = solve_pair(state, solved, slot)
        if moves is None:
            raise RuntimeError(f"no F2L solution for {slot} within 14 moves")
        cross_state = _apply(cross_state, moves)
        pair_state = {s: _apply(p, moves) for s, p in pair_state.items()}
        solved = (*solved, slot)
        steps.append(_pair_step(len(solved), slot, tuple(moves)))
    return steps


def _pair_step(index: int, slot: str, moves: tuple[str, ...]) -> Step:
    corner, edge = SLOTS[slot]
    return Step(
        f"F2L {index}",
        moves,
        f"Pair the {corner} corner with the {edge} edge and insert them.",
        case=f"{slot} slot",
    )


def best_f2l(cube: str, cross_moves: tuple[str, ...]) -> list[Step]:
    """The slot order (of 24) with the fewest total F2L moves.

    Depth-first over orders, so orders with a common prefix share work, plus
    branch-and-bound: each pair search is capped by what is left of the best
    total found so far, so hopeless orders die early. Each pair is solved
    optimally given its predecessors: this is the best pair-by-pair F2L.
    """
    cross_state = _apply(tuple(locate(cube, p) for p in CROSS), list(cross_moves))
    start_pairs = {s: _apply(tuple(locate(cube, p) for p in SLOTS[s]), list(cross_moves)) for s in SLOTS}

    # Seed the bound with the default order so pruning starts immediately.
    best_steps = solve_f2l(cube, cross_moves, tuple(SLOTS))
    best_total = sum(s.move_count for s in best_steps)

    def explore(
        cross: tuple[int, ...],
        pairs: dict[str, tuple[int, ...]],
        solved: tuple[str, ...],
        done: list[tuple[str, tuple[str, ...]]],
        total: int,
    ) -> None:
        nonlocal best_steps, best_total
        remaining = [s for s in SLOTS if s not in solved]
        if not remaining:
            if total < best_total:
                best_total = total
                best_steps = [_pair_step(i + 1, slot, mv) for i, (slot, mv) in enumerate(done)]
            return
        for slot in remaining:
            budget = best_total - total - 1  # must strictly beat the best
            if budget < 0:
                return
            state = cross + sum((pairs[s] for s in solved), ()) + pairs[slot]
            mv = solve_pair(state, solved, slot, max_depth=min(14, budget))
            if mv is None:
                continue
            explore(
                _apply(cross, mv),
                {s: _apply(p, mv) for s, p in pairs.items()},
                (*solved, slot),
                [*done, (slot, tuple(mv))],
                total + len(mv),
            )

    explore(cross_state, start_pairs, (), [], 0)
    return best_steps


def _explain(case: Case) -> str:
    if case.kind == "OLL":
        if not case.algorithm:
            return "The top face is already one color: OLL skip."
        return "Make the whole top face one color."
    if not case.algorithm:
        return "Turn the top layer into place." if case.finish else "Already solved: PLL skip."
    return "Move the top-layer pieces to their final spots."


def _last_layer_step(case: Case) -> Step:
    return Step(case.kind, tuple(case.moves.split()), _explain(case), case=case.label)


def solve(cube: str, *, best: bool = False) -> list[Step]:
    """Full CFOP: cross, four F2L pairs, OLL, PLL. `best` searches all 24 F2L orders.

    Every stage is checked as it's applied, and the final cube must be solved.
    """
    cross = solve_cross(cube)
    f2l = best_f2l(cube, cross.moves) if best else solve_f2l(cube, cross.moves, tuple(SLOTS))

    state = apply_moves(cube, " ".join(cross.moves + sum((s.moves for s in f2l), ())))
    if not all(locate(state, p) == home(p) for p in F2L_PIECES):
        raise RuntimeError("F2L stage left the first two layers unsolved")

    oll = recognize_oll(state)
    state = apply_case(state, oll)
    pll = recognize_pll(state)
    state = apply_case(state, pll)
    if state != SOLVED:
        raise RuntimeError("CFOP finished without solving the cube")

    return [cross, *f2l, _last_layer_step(oll), _last_layer_step(pll)]
