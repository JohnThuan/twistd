from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from twistd import __version__
from twistd.batching import Batcher, QueueFullError
from twistd.config import Settings
from twistd.cube import InvalidCubeError, normalize, validate_facelets
from twistd.metrics import Metrics
from twistd.schemas import ErrorResponse, HealthResponse, SolveRequest, SolveResponse
from twistd.solvers import Solver, get_solver

logger = logging.getLogger("twistd")

_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Settings default to the environment, read at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or Settings.from_env()
        logging.basicConfig(
            level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        solver = get_solver(cfg.solver)
        started = time.perf_counter()
        solver.warmup()
        logger.info(
            "solver ready solver=%s warmup_ms=%.1f batching=%s",
            solver.name,
            (time.perf_counter() - started) * 1000,
            cfg.batching,
        )

        batcher: Batcher | None = None
        if cfg.batching:
            batcher = Batcher(
                solver,
                max_batch_size=cfg.batch_max_size,
                max_wait_ms=cfg.batch_max_wait_ms,
                max_queue=cfg.batch_queue_max,
                workers=cfg.batch_workers,
            )
            await batcher.start()

        app.state.solver = solver
        app.state.batcher = batcher
        app.state.metrics = Metrics()
        try:
            yield
        finally:
            if batcher is not None:
                await batcher.stop()

    app = FastAPI(title="twistd", version=__version__, lifespan=lifespan)

    @app.exception_handler(InvalidCubeError)
    async def invalid_cube_handler(request: Request, exc: InvalidCubeError) -> JSONResponse:
        request.app.state.metrics.rejected_invalid += 1
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(QueueFullError)
    async def overload_handler(request: Request, exc: QueueFullError) -> JSONResponse:
        request.app.state.metrics.rejected_overload += 1
        return JSONResponse(
            status_code=503, content={"detail": str(exc)}, headers={"Retry-After": "1"}
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Report malformed bodies as 400 (not FastAPI's default 422), consistent with bad cubes.
        request.app.state.metrics.rejected_invalid += 1
        messages = [
            f"{'.'.join(str(p) for p in err['loc'] if p != 'body') or 'body'}: {err['msg']}"
            for err in exc.errors()
        ]
        return JSONResponse(status_code=400, content={"detail": "; ".join(messages)})

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/metrics")
    def metrics(request: Request) -> dict[str, object]:
        batcher: Batcher | None = request.app.state.batcher
        return request.app.state.metrics.snapshot(
            batching=batcher is not None,
            queue_depth=batcher.queue_depth if batcher else 0,
        )

    @app.post("/solve", response_model=SolveResponse, responses=_ERRORS)
    async def solve(body: SolveRequest, request: Request) -> SolveResponse:
        received = time.perf_counter()
        cube = normalize(body.cube)
        validate_facelets(cube)

        solver: Solver = request.app.state.solver
        batcher: Batcher | None = request.app.state.batcher
        if batcher is not None:
            result = await batcher.submit(cube)
            solution, solve_ms = result.solution, result.solve_ms
            queue_ms, batch_size = result.queue_ms, result.batch_size
        else:
            # The solver is CPU-bound; run it in the threadpool so the event loop stays free.
            started = time.perf_counter()
            solution = await run_in_threadpool(solver.solve, cube)
            solve_ms = (time.perf_counter() - started) * 1000
            queue_ms, batch_size = 0.0, 1

        total_ms = (time.perf_counter() - received) * 1000
        move_count = len(solution.split())
        request.app.state.metrics.record_solve(
            total_ms=total_ms, solve_ms=solve_ms, queue_ms=queue_ms, batch_size=batch_size
        )
        logger.info(
            "solve solver=%s moves=%d solve_ms=%.3f queue_ms=%.3f batch=%d total_ms=%.3f",
            solver.name,
            move_count,
            solve_ms,
            queue_ms,
            batch_size,
            total_ms,
        )
        return SolveResponse(
            solution=solution,
            move_count=move_count,
            solver=solver.name,
            solve_ms=round(solve_ms, 3),
        )

    return app


app = create_app()
