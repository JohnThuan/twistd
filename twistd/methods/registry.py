"""The teaching methods the API exposes, and how worker processes get ready for them.

The teaching solvers are pure Python, so they hold the GIL: on threads they'd
share one core. The API runs them in a process pool instead; `warmup` is that
pool's initializer, loading the lookup tables once per worker process.
(Tables are copied into each process rather than memory-mapped: a shared mmap
measured ~1.5x slower per lookup, and the copy costs ~64 MB per worker.)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Literal

from twistd.methods import beginner, cfop, last_layer
from twistd.methods.cfop import Step

Method = Literal["optimal", "beginner", "cfop", "cfop-best"]
METHODS: Final[tuple[Method, ...]] = ("optimal", "beginner", "cfop", "cfop-best")

DESCRIPTIONS: Final[dict[Method, str]] = {
    "optimal": "Fewest moves (about 20). Fast, but not something a person can learn from.",
    "beginner": "Layer by layer in 7 stages, using the algorithms beginners learn first.",
    "cfop": "The speedcubing method, the way people do it: U/R/L/F turns plus cube rotations.",
    "cfop-best": "CFOP with the fewest moves: best of all 24 F2L orders, any face turns.",
}

TEACHING: Final[dict[Method, Callable[[str], list[Step]]]] = {
    "beginner": beginner.solve,
    "cfop": cfop.solve_human,
    "cfop-best": lambda cube: cfop.solve(cube, best=True),
}


def warmup() -> None:
    """Load every table the teaching methods use, so no request pays for it."""
    cfop.warmup()
    last_layer.oll_table()
    last_layer.pll_table()
    for method in TEACHING:
        solve_teaching(method, _WARMUP_CUBE)


def solve_teaching(method: Method, cube: str) -> list[Step]:
    """Module-level so a process pool can pickle a reference to it."""
    try:
        solve = TEACHING[method]
    except KeyError:
        raise ValueError(f"not a teaching method: {method!r}") from None
    return solve(cube)


# Same example cube the Kociemba warmup uses.
_WARMUP_CUBE: Final = "DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD"
