from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None else float(raw)


@dataclass(frozen=True)
class Settings:
    solver: str = "kociemba"
    log_level: str = "INFO"
    batching: bool = True
    batch_max_size: int = 32
    batch_max_wait_ms: float = 2.0
    batch_queue_max: int = 1024
    batch_workers: int = 4

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            solver=os.getenv("SOLVER", cls.solver).strip().lower(),
            log_level=os.getenv("LOG_LEVEL", cls.log_level).strip().upper(),
            batching=_env_bool("BATCHING", cls.batching),
            batch_max_size=_env_int("BATCH_MAX_SIZE", cls.batch_max_size),
            batch_max_wait_ms=_env_float("BATCH_MAX_WAIT_MS", cls.batch_max_wait_ms),
            batch_queue_max=_env_int("BATCH_QUEUE_MAX", cls.batch_queue_max),
            batch_workers=_env_int("BATCH_WORKERS", cls.batch_workers),
        )
