from __future__ import annotations

import kociemba

from twistd.cube import SOLVED, UnsolvableCubeError
from twistd.solvers.base import Solver

# Example state from the kociemba README; used to load pruning tables at startup.
_WARMUP_CUBE = "DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD"


class KociembaSolver(Solver):
    name = "kociemba"

    def warmup(self) -> None:
        kociemba.solve(_WARMUP_CUBE)

    def solve(self, cube: str) -> str:
        # kociemba's output for the identity state isn't an empty sequence, so short-circuit.
        if cube == SOLVED:
            return ""
        try:
            return str(kociemba.solve(cube)).strip()
        except ValueError as exc:
            raise UnsolvableCubeError(
                "cube state is not solvable (twisted corner, flipped edge, or parity error)"
            ) from exc
