import asyncio
import threading
import time

import pytest

from twistd.config import Settings
from twistd.cube import SOLVED, UnsolvableCubeError, apply_moves
from twistd.service import (
    LRUCache,
    OverloadedError,
    SolverFaultError,
    SolveService,
    SolveTimeoutError,
)
from twistd.solvers import Solver

SCRAMBLED = apply_moves(SOLVED, "R U F'")
SOLUTION = "F U' R'"


class FakeSolver(Solver):
    name = "fake"

    def __init__(self, answer: str = SOLUTION, delay_s: float = 0.0) -> None:
        self.answer = answer
        self.delay_s = delay_s
        self.calls = 0
        self.gate = threading.Event()
        self.gate.set()

    def solve(self, cube: str) -> str:
        self.calls += 1
        self.gate.wait(timeout=5)
        time.sleep(self.delay_s)
        if cube == "bad":
            raise UnsolvableCubeError("unsolvable")
        return self.answer


def _settings(**overrides: object) -> Settings:
    base = {"solver_threads": 2, "batching": "off", "solve_timeout_s": 5.0}
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


async def _with_service(solver: Solver, settings: Settings, fn):  # type: ignore[no-untyped-def]
    service = SolveService(solver, settings)
    await service.start()
    try:
        return await fn(service)
    finally:
        await service.stop()


@pytest.mark.parametrize("batching", ["on", "off"])
def test_solves_and_reports_timing(batching: str) -> None:
    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        return await service.solve(SCRAMBLED)

    result = asyncio.run(_with_service(FakeSolver(), _settings(batching=batching), run))
    assert result.solution == SOLUTION
    assert result.solve_ms >= 0 and result.queue_ms >= 0
    assert not result.cached


def test_repeat_cube_is_served_from_cache() -> None:
    solver = FakeSolver()

    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        first = await service.solve(SCRAMBLED)
        second = await service.solve(SCRAMBLED)
        return first, second, service.cache_hits

    first, second, hits = asyncio.run(_with_service(solver, _settings(), run))
    assert solver.calls == 1
    assert not first.cached and second.cached
    assert second.solution == SOLUTION and hits == 1


def test_cache_can_be_disabled() -> None:
    solver = FakeSolver()

    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        await service.solve(SCRAMBLED)
        await service.solve(SCRAMBLED)

    asyncio.run(_with_service(solver, _settings(cache_size=0), run))
    assert solver.calls == 2


def test_wrong_solution_is_never_returned_or_cached() -> None:
    solver = FakeSolver(answer="U")  # does not solve SCRAMBLED

    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        with pytest.raises(SolverFaultError):
            await service.solve(SCRAMBLED)
        return len(service.cache)

    assert asyncio.run(_with_service(solver, _settings(), run)) == 0


def test_unsolvable_cube_error_propagates() -> None:
    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        with pytest.raises(UnsolvableCubeError):
            await service.solve("bad")

    asyncio.run(_with_service(FakeSolver(), _settings(), run))


@pytest.mark.parametrize("batching", ["on", "off"])
def test_slow_solve_times_out(batching: str) -> None:
    solver = FakeSolver(delay_s=0.5)

    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        with pytest.raises(SolveTimeoutError):
            await service.solve(SCRAMBLED)

    asyncio.run(_with_service(solver, _settings(batching=batching, solve_timeout_s=0.1), run))


def test_timed_out_work_still_holds_its_slot_until_it_finishes() -> None:
    solver = FakeSolver(delay_s=0.3)

    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        with pytest.raises(SolveTimeoutError):
            await service.solve(SCRAMBLED)
        still_running = service.pending
        await asyncio.sleep(0.4)
        return still_running, service.pending

    during, after = asyncio.run(
        _with_service(solver, _settings(solve_timeout_s=0.1, cache_size=0), run)
    )
    assert during == 1 and after == 0


def test_overload_is_rejected_fast() -> None:
    solver = FakeSolver()
    solver.gate.clear()  # hold every solve so requests pile up

    async def run(service: SolveService):  # type: ignore[no-untyped-def]
        tasks = [asyncio.create_task(service.solve(SCRAMBLED)) for _ in range(5)]
        await asyncio.sleep(0.05)
        solver.gate.set()
        return await asyncio.gather(*tasks, return_exceptions=True)

    results = asyncio.run(_with_service(solver, _settings(max_pending=2, cache_size=0), run))
    assert sum(isinstance(r, OverloadedError) for r in results) == 3
    assert sum(not isinstance(r, Exception) for r in results) == 2


def test_auto_batching_follows_the_solver() -> None:
    class Vectorized(FakeSolver):
        vectorized = True

    assert not SolveService(FakeSolver(), _settings(batching="auto")).batching
    assert SolveService(Vectorized(), _settings(batching="auto")).batching
    assert SolveService(FakeSolver(), _settings(batching="on")).batching


def test_lru_cache_evicts_least_recently_used() -> None:
    cache = LRUCache(2)
    cache.put("a", "1")
    cache.put("b", "2")
    assert cache.get("a") == "1"  # "b" is now least recent
    cache.put("c", "3")
    assert cache.get("b") is None
    assert cache.get("a") == "1" and cache.get("c") == "3"
    assert len(cache) == 2
