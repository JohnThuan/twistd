"""In-process request metrics over a rolling window, served at GET /metrics.

Only touched from the event loop, so no locking is needed.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class _Sample:
    at: float
    total_ms: float
    solve_ms: float
    queue_ms: float
    batch_size: int


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "p50": round(percentile(values, 50), 3),
        "p95": round(percentile(values, 95), 3),
        "p99": round(percentile(values, 99), 3),
        "max": round(max(values, default=0.0), 3),
    }


class Metrics:
    def __init__(self, window: int = 10_000, rate_window_s: float = 60.0) -> None:
        self._samples: deque[_Sample] = deque(maxlen=window)
        self._rate_window_s = rate_window_s
        self._started = time.monotonic()
        self.solved = 0
        self.rejected_invalid = 0
        self.rejected_overload = 0

    def record_solve(
        self, *, total_ms: float, solve_ms: float, queue_ms: float = 0.0, batch_size: int = 1
    ) -> None:
        self.solved += 1
        self._samples.append(_Sample(time.monotonic(), total_ms, solve_ms, queue_ms, batch_size))

    def snapshot(self, *, batching: bool, queue_depth: int = 0) -> dict[str, object]:
        now = time.monotonic()
        samples = list(self._samples)
        recent = [s for s in samples if now - s.at <= self._rate_window_s]
        span = min(self._rate_window_s, now - self._started) or 1.0
        return {
            "uptime_s": round(now - self._started, 1),
            "requests": {
                "solved": self.solved,
                "rejected_invalid": self.rejected_invalid,
                "rejected_overload": self.rejected_overload,
            },
            "throughput_rps": round(len(recent) / span, 2),
            "window_size": len(samples),
            "latency_ms": {
                "total": _summary([s.total_ms for s in samples]),
                "solve": _summary([s.solve_ms for s in samples]),
                "queue": _summary([s.queue_ms for s in samples]),
            },
            "batching": {
                "enabled": batching,
                "avg_batch_size": round(
                    sum(s.batch_size for s in samples) / len(samples), 2
                )
                if samples
                else 0.0,
                "queue_depth": queue_depth,
            },
        }
