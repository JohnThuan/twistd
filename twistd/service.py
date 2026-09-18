"""The solve pipeline behind POST /solve, independent of HTTP.

cache lookup -> admission control -> solver (thread pool, optionally batched)
-> timeout -> verify the solution -> cache store.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from twistd.batching import Batcher, QueueFullError
from twistd.config import Settings
from twistd.cube import SOLVED, apply_moves
from twistd.solvers import Solver

logger = logging.getLogger("twistd.service")


class OverloadedError(RuntimeError):
    """Too many solves in flight; shed load (503)."""


class SolveTimeoutError(RuntimeError):
    """The solver did not finish within the configured budget (504)."""


class SolverFaultError(RuntimeError):
    """The solver returned a sequence that does not solve the cube (500)."""


@dataclass(frozen=True)
class SolveResult:
    solution: str
    solve_ms: float
    queue_ms: float
    batch_size: int
    cached: bool


class LRUCache:
    """Bounded mapping that evicts the least recently used entry. O(1) get/put."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._data: OrderedDict[str, str] = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str) -> str | None:
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    def put(self, key: str, value: str) -> None:
        if self.capacity <= 0:
            return
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)


class SolveService:
    def __init__(self, solver: Solver, settings: Settings) -> None:
        self.solver = solver
        self.settings = settings
        self.threads = settings.solver_threads
        self.batching = settings.batching == "on" or (
            settings.batching == "auto" and solver.vectorized
        )
        self.cache = LRUCache(settings.cache_size)
        self.cache_hits = 0
        self._pending = 0
        self._executor = ThreadPoolExecutor(
            max_workers=self.threads, thread_name_prefix="solver"
        )
        self._batcher: Batcher | None = None
        if self.batching:
            self._batcher = Batcher(
                solver,
                max_batch_size=settings.batch_max_size,
                max_wait_ms=settings.batch_max_wait_ms,
                max_queue=settings.max_pending,
                workers=self.threads,
                executor=self._executor,
            )

    @property
    def pending(self) -> int:
        return self._pending

    async def start(self) -> None:
        if self._batcher is not None:
            await self._batcher.start()

    async def stop(self) -> None:
        if self._batcher is not None:
            await self._batcher.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def solve(self, cube: str) -> SolveResult:
        """Solve a structurally valid cube. Raises InvalidCubeError for unsolvable states."""
        cached = self.cache.get(cube)
        if cached is not None:
            self.cache_hits += 1
            return SolveResult(cached, 0.0, 0.0, 0, cached=True)

        if self._pending >= self.settings.max_pending:
            raise OverloadedError("server is at capacity, retry shortly")

        if self._batcher is not None:
            result = await self._solve_batched(cube)
        else:
            result = await self._solve_direct(cube)

        # ~20 us against a ~15 ms solve: never return a wrong answer.
        if apply_moves(cube, result.solution) != SOLVED:
            logger.error("solver returned a non-solution solver=%s", self.solver.name)
            raise SolverFaultError("solver produced an invalid solution")

        self.cache.put(cube, result.solution)
        return result

    async def _solve_direct(self, cube: str) -> SolveResult:
        loop = asyncio.get_running_loop()
        submitted = time.perf_counter()
        future = loop.run_in_executor(self._executor, self._timed_solve, cube, submitted)

        # A timed-out solve keeps its thread until the C code returns, so the slot is
        # released when the work actually ends, not when the client stops waiting.
        self._pending += 1
        future.add_done_callback(self._release)
        try:
            solution, solve_ms, queue_ms = await asyncio.wait_for(
                asyncio.shield(future), self.settings.solve_timeout_s
            )
        except TimeoutError:
            raise SolveTimeoutError(
                f"solve exceeded {self.settings.solve_timeout_s:g}s"
            ) from None
        return SolveResult(solution, solve_ms, queue_ms, 1, cached=False)

    def _timed_solve(self, cube: str, submitted: float) -> tuple[str, float, float]:
        started = time.perf_counter()
        solution = self.solver.solve(cube)
        finished = time.perf_counter()
        return solution, (finished - started) * 1000, (started - submitted) * 1000

    def _release(self, future: asyncio.Future[object]) -> None:
        self._pending -= 1
        if not future.cancelled():
            future.exception()  # mark retrieved; the awaiting caller may have timed out

    async def _solve_batched(self, cube: str) -> SolveResult:
        assert self._batcher is not None
        self._pending += 1
        try:
            result = await asyncio.wait_for(
                self._batcher.submit(cube), self.settings.solve_timeout_s
            )
        except QueueFullError as exc:
            raise OverloadedError(str(exc)) from None
        except TimeoutError:
            raise SolveTimeoutError(
                f"solve exceeded {self.settings.solve_timeout_s:g}s"
            ) from None
        finally:
            self._pending -= 1
        return SolveResult(
            result.solution, result.solve_ms, result.queue_ms, result.batch_size, cached=False
        )
