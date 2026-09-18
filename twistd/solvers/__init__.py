from __future__ import annotations

from collections.abc import Callable

from twistd.solvers.base import SolveOutcome, Solver
from twistd.solvers.kociemba_solver import KociembaSolver

_REGISTRY: dict[str, Callable[[], Solver]] = {
    KociembaSolver.name: KociembaSolver,
}


def get_solver(name: str) -> Solver:
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown solver '{name}'; available: {sorted(_REGISTRY)}") from None
    return factory()


__all__ = ["SolveOutcome", "Solver", "get_solver"]
