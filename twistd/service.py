"""The solve pipeline behind POST /solve, independent of HTTP.

cache lookup -> admission control -> solver -> timeout -> verify -> cache store.

Two execution paths share that pipeline:
- "optimal" (Kociemba, C code that releases the GIL): a thread pool, optionally batched.
- teaching methods (pure Python, holds the GIL): a process pool, so they use every core.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import time
from collections import OrderedDict
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any

from twistd.batching import Batcher, QueueFullError
from twistd.config import Settings
from twistd.cube import SOLVED, apply_moves
from twistd.methods.cfop import Step
from twistd.methods.notation import to_face_turns
from twistd.methods.registry import METHODS, Method, solve_teaching, warmup
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
    method: Method
    steps: tuple[Step, ...]
    solve_ms: float
    queue_ms: float
    batch_size: int
    cached: bool

    @property
    def solution(self) -> str:
        return " ".join(" ".join(step.moves) for step in self.steps if step.moves)


class LRUCache:
    """Bounded mapping that evicts the least recently used entry. O(1) get/put."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._data: OrderedDict[str, tuple[Step, ...]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str) -> tuple[Step, ...] | None:
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    def put(self, key: str, value: tuple[Step, ...]) -> None:
        if self.capacity <= 0:
            return
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)


def _optimal_step(solution: str) -> tuple[Step, ...]:
    return (Step("Solve", tuple(solution.split()), "The shortest solution the solver found."),)


def solves(cube: str, steps: tuple[Step, ...]) -> bool:
    """Replay every step, rotations and wide moves included, on the original cube."""
    notation = " ".join(" ".join(step.moves) for step in steps)
    turns = " ".join(to_face_turns(notation)[0])
    return (apply_moves(cube, turns) if turns else cube) == SOLVED


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
        self.method_counts: dict[str, int] = dict.fromkeys(METHODS, 0)
        self._pending = 0
        self._executor = ThreadPoolExecutor(max_workers=self.threads, thread_name_prefix="solver")
        self._method_pool: Executor | None = None
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
        if self.settings.method_workers > 0:
            await self._start_method_pool()
        else:
            self._method_pool = self._executor  # dev/test mode: share the thread pool
            await asyncio.get_running_loop().run_in_executor(self._executor, warmup)

    async def _start_method_pool(self) -> None:
        workers = self.settings.method_workers
        # spawn, not fork: forking a process that already runs threads can deadlock.
        pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=warmup,
        )
        # Start every worker now so the first real request doesn't wait seconds for one.
        loop = asyncio.get_running_loop()
        await asyncio.gather(*(loop.run_in_executor(pool, _noop) for _ in range(workers)))
        self._method_pool = pool

    async def stop(self) -> None:
        if self._batcher is not None:
            await self._batcher.stop()
        if self._method_pool is not None and self._method_pool is not self._executor:
            # wait=True: let the pool's manager thread close its pipes before we exit.
            self._method_pool.shutdown(wait=True, cancel_futures=True)
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def solve(self, cube: str, method: Method = "optimal") -> SolveResult:
        """Solve a structurally valid cube. Raises InvalidCubeError for unsolvable states."""
        key = f"{method}:{cube}"
        cached = self.cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return SolveResult(method, cached, 0.0, 0.0, 0, cached=True)

        if self._pending >= self.settings.max_pending:
            raise OverloadedError("server is at capacity, retry shortly")

        if method != "optimal":
            result = await self._solve_teaching(method, cube)
        elif self._batcher is not None:
            result = await self._solve_batched(self._batcher, cube)
        else:
            result = await self._solve_direct(cube)

        # Replaying costs microseconds against milliseconds of solving: never return a wrong answer.
        if not solves(cube, result.steps):
            logger.error("solver returned a non-solution method=%s", method)
            raise SolverFaultError("solver produced an invalid solution")

        self.method_counts[method] += 1
        self.cache.put(key, result.steps)
        return result

    async def _run(self, executor: Executor, fn: Any, *args: Any) -> tuple[Any, float, float]:
        """Run fn on an executor with admission control and a timeout.

        A timed-out call keeps running (Python can't kill it), so its slot is freed
        when the work actually ends, not when the client stops waiting.
        """
        loop = asyncio.get_running_loop()
        submitted = time.perf_counter()
        future = loop.run_in_executor(executor, _timed, fn, submitted, *args)
        self._pending += 1
        future.add_done_callback(self._release)
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.settings.solve_timeout_s)
        except TimeoutError:
            raise SolveTimeoutError(f"solve exceeded {self.settings.solve_timeout_s:g}s") from None

    async def _solve_direct(self, cube: str) -> SolveResult:
        solution, solve_ms, queue_ms = await self._run(self._executor, self.solver.solve, cube)
        return SolveResult("optimal", _optimal_step(solution), solve_ms, queue_ms, 1, cached=False)

    async def _solve_teaching(self, method: Method, cube: str) -> SolveResult:
        pool = self._method_pool
        if pool is None:
            raise RuntimeError("SolveService.start() was not called")
        try:
            steps, solve_ms, queue_ms = await self._run(pool, solve_teaching, method, cube)
        except BrokenProcessPool:
            # A worker died (e.g. killed for memory). The pool is unusable from now on,
            # so replace it once, and ask this client to retry rather than fail forever.
            logger.error("teaching worker pool broke; restarting it")
            if self._method_pool is pool:
                pool.shutdown(wait=False, cancel_futures=True)
                self._method_pool = None
                await self._start_method_pool()
            raise OverloadedError("solver restarting, retry shortly") from None
        return SolveResult(method, tuple(steps), solve_ms, queue_ms, 1, cached=False)

    def _release(self, future: asyncio.Future[Any]) -> None:
        self._pending -= 1
        if not future.cancelled():
            future.exception()  # mark retrieved; the awaiting caller may have timed out

    async def _solve_batched(self, batcher: Batcher, cube: str) -> SolveResult:
        self._pending += 1
        try:
            result = await asyncio.wait_for(batcher.submit(cube), self.settings.solve_timeout_s)
        except QueueFullError as exc:
            raise OverloadedError(str(exc)) from None
        except TimeoutError:
            raise SolveTimeoutError(f"solve exceeded {self.settings.solve_timeout_s:g}s") from None
        finally:
            self._pending -= 1
        return SolveResult(
            "optimal",
            _optimal_step(result.solution),
            result.solve_ms,
            result.queue_ms,
            result.batch_size,
            cached=False,
        )


def _noop() -> None:
    """Forces a pool worker to start (and run its initializer)."""


def _timed(fn: Any, submitted: float, *args: Any) -> tuple[Any, float, float]:
    """Runs in the worker: returns (result, solve_ms, queue_ms)."""
    started = time.perf_counter()
    result = fn(*args)
    finished = time.perf_counter()
    return result, (finished - started) * 1000, (started - submitted) * 1000
