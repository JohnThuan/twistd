from __future__ import annotations

from collections.abc import Callable

from rubiserve.solvers.base import Solver
from rubiserve.solvers.kociemba_solver import KociembaSolver

_REGISTRY: dict[str, Callable[[], Solver]] = {
    KociembaSolver.name: KociembaSolver,
}


def get_solver(name: str) -> Solver:
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown solver '{name}'; available: {sorted(_REGISTRY)}") from None
    return factory()


__all__ = ["Solver", "get_solver"]
