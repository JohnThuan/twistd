from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

BatchingMode = Literal["auto", "on", "off"]


def available_cpus() -> int:
    """CPUs this process may actually use, honoring affinity and cgroup quotas.

    `os.cpu_count()` reports the host's cores; inside a container limited to
    e.g. 1 vCPU (ECS Fargate, `docker run --cpus`), sizing a thread pool from it
    would oversubscribe the CPU and hurt tail latency.
    """
    affinity = getattr(os, "sched_getaffinity", None)  # Linux only
    cpus = len(affinity(0)) if affinity else (os.cpu_count() or 1)

    quota = _cgroup_cpu_quota()
    if quota is not None:
        cpus = min(cpus, max(1, math.ceil(quota)))
    return max(1, cpus)


def default_method_workers() -> int:
    return min(available_cpus(), 4)


def _cgroup_cpu_quota() -> float | None:
    try:  # cgroup v2: "<quota> <period>" or "max <period>"
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        return None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        quota_us = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period_us = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        return None if quota_us <= 0 else quota_us / period_us
    except (OSError, ValueError):
        return None


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    solver: str = "kociemba"
    log_level: str = "INFO"
    # Threads that run the (GIL-releasing, CPU-bound) solver. Defaults to usable CPUs.
    solver_threads: int = field(default_factory=available_cpus)
    # Processes for the pure-Python teaching methods (0 = run them on the thread pool).
    # Each holds ~100 MB of lookup tables, so the default is capped rather than one per CPU.
    method_workers: int = field(default_factory=lambda: default_method_workers())
    # "auto" batches only for solvers that can vectorize a batch (e.g. a neural net).
    batching: BatchingMode = "auto"
    batch_max_size: int = 32
    batch_max_wait_ms: float = 2.0
    # Solves admitted at once (running + waiting). Past this, /solve returns 503.
    max_pending: int = 512
    solve_timeout_s: float = 10.0
    # LRU cache of verified solutions; 0 disables it.
    cache_size: int = 10_000
    max_body_bytes: int = 1024
    docs_enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        batching = _env_str("BATCHING", "auto").lower()
        if batching in {"true", "1", "yes"}:
            batching = "on"
        elif batching in {"false", "0", "no"}:
            batching = "off"
        if batching not in {"auto", "on", "off"}:
            raise ValueError(f"BATCHING must be auto, on or off, got {batching!r}")

        return cls(
            solver=_env_str("SOLVER", cls.solver).lower(),
            log_level=_env_str("LOG_LEVEL", cls.log_level).upper(),
            solver_threads=_env_int("SOLVER_THREADS", available_cpus(), minimum=1),
            method_workers=_env_int("METHOD_WORKERS", default_method_workers()),
            batching=batching,  # type: ignore[arg-type]
            batch_max_size=_env_int("BATCH_MAX_SIZE", cls.batch_max_size, minimum=1),
            batch_max_wait_ms=_env_float("BATCH_MAX_WAIT_MS", cls.batch_max_wait_ms),
            max_pending=_env_int("MAX_PENDING", cls.max_pending, minimum=1),
            solve_timeout_s=_env_float("SOLVE_TIMEOUT_S", cls.solve_timeout_s, minimum=0.1),
            cache_size=_env_int("CACHE_SIZE", cls.cache_size),
            max_body_bytes=_env_int("MAX_BODY_BYTES", cls.max_body_bytes, minimum=128),
            docs_enabled=_env_bool("DOCS_ENABLED", cls.docs_enabled),
        )
