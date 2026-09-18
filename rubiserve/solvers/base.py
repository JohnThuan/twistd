from __future__ import annotations

from typing import Protocol


class Solver(Protocol):
    """A cube-solving backend.

    `solve` receives a facelet string that has already passed structural validation
    and returns a space-separated move sequence (empty for an already-solved cube).
    It raises `UnsolvableCubeError` for well-formed but unreachable states.
    """

    name: str

    def warmup(self) -> None:
        """Load tables/models so the first request doesn't pay the cost."""
        ...

    def solve(self, cube: str) -> str: ...
