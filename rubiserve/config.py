from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    solver: str = "kociemba"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            solver=os.getenv("SOLVER", cls.solver).strip().lower(),
            log_level=os.getenv("LOG_LEVEL", cls.log_level).strip().upper(),
        )
