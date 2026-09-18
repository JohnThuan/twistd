import asyncio
import threading
import time
from collections.abc import Sequence

import pytest

from twistd.batching import Batcher, QueueFullError
from twistd.cube import UnsolvableCubeError
from twistd.solvers import SolveOutcome, Solver


class RecordingSolver(Solver):
    """Echoes the cube back as its 'solution' and records every batch it sees."""

    name = "fake"

    def __init__(self, delay_s: float = 0.0) -> None:
        self.batches: list[list[str]] = []
        self.delay_s = delay_s
        self.release = threading.Event()
        self.release.set()

    def solve(self, cube: str) -> str:
        if cube == "bad":
            raise UnsolvableCubeError("unsolvable")
        return f"solved:{cube}"

    def solve_batch(self, cubes: Sequence[str]) -> list[SolveOutcome]:
        self.release.wait(timeout=5)
        time.sleep(self.delay_s)
        self.batches.append(list(cubes))
        return super().solve_batch(cubes)


async def _run(batcher: Batcher, cubes: list[str]) -> list[object]:
    await batcher.start()
    try:
        return await asyncio.gather(
            *(batcher.submit(c) for c in cubes), return_exceptions=True
        )
    finally:
        await batcher.stop()


def test_concurrent_requests_share_a_batch() -> None:
    solver = RecordingSolver()
    batcher = Batcher(solver, max_batch_size=8, max_wait_ms=50)
    results = asyncio.run(_run(batcher, [f"c{i}" for i in range(5)]))

    assert solver.batches == [["c0", "c1", "c2", "c3", "c4"]]
    assert [r.solution for r in results] == [f"solved:c{i}" for i in range(5)]
    assert all(r.batch_size == 5 for r in results)


def test_batches_are_capped_at_max_size() -> None:
    solver = RecordingSolver()
    batcher = Batcher(solver, max_batch_size=4, max_wait_ms=50)
    results = asyncio.run(_run(batcher, [f"c{i}" for i in range(10)]))

    assert [len(b) for b in solver.batches] == [4, 4, 2]
    assert sorted(r.solution for r in results) == sorted(f"solved:c{i}" for i in range(10))


def test_lone_request_is_flushed_after_max_wait() -> None:
    solver = RecordingSolver()
    batcher = Batcher(solver, max_batch_size=32, max_wait_ms=5)
    started = time.perf_counter()
    [result] = asyncio.run(_run(batcher, ["only"]))

    assert result.solution == "solved:only"
    assert result.batch_size == 1
    assert time.perf_counter() - started < 1.0


def test_one_bad_cube_does_not_fail_its_batch() -> None:
    solver = RecordingSolver()
    batcher = Batcher(solver, max_batch_size=8, max_wait_ms=50)
    results = asyncio.run(_run(batcher, ["a", "bad", "b"]))

    assert len(solver.batches) == 1
    assert results[0].solution == "solved:a"
    assert isinstance(results[1], UnsolvableCubeError)
    assert results[2].solution == "solved:b"


def test_full_queue_rejects_instead_of_waiting() -> None:
    async def scenario() -> list[object]:
        solver = RecordingSolver()
        solver.release.clear()  # block the solver so the queue backs up
        batcher = Batcher(solver, max_batch_size=1, max_wait_ms=0, max_queue=2, workers=1)
        await batcher.start()
        try:
            tasks = [asyncio.create_task(batcher.submit(f"c{i}")) for i in range(6)]
            await asyncio.sleep(0.05)
            solver.release.set()
            return await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await batcher.stop()

    results = asyncio.run(scenario())
    rejected = [r for r in results if isinstance(r, QueueFullError)]
    solved = [r for r in results if not isinstance(r, Exception)]
    assert rejected, "expected some requests to be shed"
    assert len(rejected) + len(solved) == 6


def test_solver_crash_fails_the_batch_instead_of_hanging() -> None:
    class CrashingSolver(RecordingSolver):
        def solve_batch(self, cubes: Sequence[str]) -> list[SolveOutcome]:
            raise RuntimeError("boom")

    batcher = Batcher(CrashingSolver(), max_batch_size=8, max_wait_ms=10)
    results = asyncio.run(_run(batcher, ["a", "b"]))
    assert all(isinstance(r, RuntimeError) for r in results)


def test_multiple_batches_run_concurrently() -> None:
    solver = RecordingSolver(delay_s=0.2)
    batcher = Batcher(solver, max_batch_size=1, max_wait_ms=0, workers=4)
    started = time.perf_counter()
    asyncio.run(_run(batcher, [f"c{i}" for i in range(4)]))

    # Four 200 ms batches on four workers should overlap, not take ~800 ms.
    assert time.perf_counter() - started < 0.6


@pytest.mark.parametrize("kwargs", [{"max_batch_size": 0}, {"workers": 0}, {"max_queue": 0}])
def test_rejects_nonsense_config(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Batcher(RecordingSolver(), **kwargs)
