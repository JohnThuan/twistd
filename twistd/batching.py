"""Micro-batching: group concurrent /solve requests and hand them to the solver together.

Requests are queued; a collector task pulls the first waiting job, then keeps pulling
until the batch is full or `max_wait_ms` has passed since that first job arrived.
Each batch runs in a worker thread (the solver is CPU-bound), and up to `workers`
batches can be in flight at once. A bounded queue gives backpressure: when it is
full, `submit` fails fast instead of letting latency grow without limit.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from twistd.solvers import Solver

logger = logging.getLogger("twistd.batching")


class QueueFullError(RuntimeError):
    """The batch queue is at capacity; the caller should shed load (503)."""


@dataclass(frozen=True)
class BatchResult:
    solution: str
    solve_ms: float
    queue_ms: float
    batch_size: int


@dataclass
class _Job:
    cube: str
    future: asyncio.Future[BatchResult]
    enqueued_at: float = field(default_factory=time.perf_counter)


class Batcher:
    def __init__(
        self,
        solver: Solver,
        *,
        max_batch_size: int = 32,
        max_wait_ms: float = 2.0,
        max_queue: int = 1024,
        workers: int = 4,
    ) -> None:
        if max_batch_size < 1 or workers < 1 or max_queue < 1:
            raise ValueError("max_batch_size, workers and max_queue must be >= 1")
        self.solver = solver
        self.max_batch_size = max_batch_size
        self.max_wait_s = max_wait_ms / 1000
        self._queue: asyncio.Queue[_Job] = asyncio.Queue(maxsize=max_queue)
        self._slots = asyncio.Semaphore(workers)
        self._collector: asyncio.Task[None] | None = None
        self._in_flight: set[asyncio.Task[None]] = set()

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        if self._collector is None:
            self._collector = asyncio.create_task(self._collect(), name="batch-collector")

    async def stop(self) -> None:
        if self._collector is not None:
            self._collector.cancel()
            await asyncio.gather(self._collector, return_exceptions=True)
            self._collector = None
        await asyncio.gather(*self._in_flight, return_exceptions=True)
        while not self._queue.empty():
            job = self._queue.get_nowait()
            if not job.future.done():
                job.future.set_exception(RuntimeError("batcher stopped"))

    async def submit(self, cube: str) -> BatchResult:
        """Queue one cube and wait for its result. Raises the cube's InvalidCubeError."""
        job = _Job(cube, asyncio.get_running_loop().create_future())
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            raise QueueFullError("solve queue is full, try again shortly") from None
        return await job.future

    async def _collect(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            batch = [await self._queue.get()]
            deadline = loop.time() + self.max_wait_s
            while len(batch) < self.max_batch_size:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self._queue.get(), remaining))
                except TimeoutError:
                    break

            await self._slots.acquire()
            task = asyncio.create_task(self._run(batch))
            self._in_flight.add(task)
            task.add_done_callback(self._in_flight.discard)

    async def _run(self, batch: list[_Job]) -> None:
        try:
            dispatched_at = time.perf_counter()
            try:
                outcomes = await asyncio.to_thread(
                    self.solver.solve_batch, [job.cube for job in batch]
                )
            except Exception as exc:  # a solver bug must not hang every waiting request
                logger.exception("batch of %d failed", len(batch))
                for job in batch:
                    if not job.future.done():
                        job.future.set_exception(exc)
                return

            for job, outcome in zip(batch, outcomes, strict=True):
                if job.future.done():  # client went away
                    continue
                if outcome.error is not None:
                    job.future.set_exception(outcome.error)
                    continue
                assert outcome.solution is not None
                job.future.set_result(
                    BatchResult(
                        solution=outcome.solution,
                        solve_ms=outcome.solve_ms,
                        queue_ms=(dispatched_at - job.enqueued_at) * 1000,
                        batch_size=len(batch),
                    )
                )
        finally:
            self._slots.release()


__all__ = ["BatchResult", "Batcher", "QueueFullError"]
