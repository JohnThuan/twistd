from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from twistd.cube import InvalidCubeError


@dataclass(frozen=True)
class SolveOutcome:
    """Result for one cube in a batch: either a solution or the error it raised."""

    solution: str | None
    error: InvalidCubeError | None
    solve_ms: float


class Solver(ABC):
    """A cube-solving backend.

    `solve` receives a facelet string that has already passed structural validation
    and returns a space-separated move sequence (empty for an already-solved cube).
    It raises `UnsolvableCubeError` for well-formed but unreachable states.
    """

    name: str

    def warmup(self) -> None:
        """Load tables/models so the first request doesn't pay the cost."""

    @abstractmethod
    def solve(self, cube: str) -> str: ...

    def solve_batch(self, cubes: Sequence[str]) -> list[SolveOutcome]:
        """Solve several cubes. Errors are returned per cube, never raised.

        The default just loops; backends that can vectorize (e.g. a neural net
        scoring many states in one forward pass) should override this.
        """
        outcomes = []
        for cube in cubes:
            started = time.perf_counter()
            try:
                solution, error = self.solve(cube), None
            except InvalidCubeError as exc:
                solution, error = None, exc
            elapsed = (time.perf_counter() - started) * 1000
            outcomes.append(SolveOutcome(solution, error, elapsed))
        return outcomes
