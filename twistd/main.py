from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from twistd import __version__
from twistd.config import Settings
from twistd.cube import InvalidCubeError, normalize, validate_facelets
from twistd.methods.notation import move_count
from twistd.metrics import Metrics
from twistd.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from twistd.schemas import ErrorResponse, HealthResponse, SolveRequest, SolveResponse, StepOut
from twistd.service import (
    OverloadedError,
    SolverFaultError,
    SolveService,
    SolveTimeoutError,
)
from twistd.solvers import get_solver

logger = logging.getLogger("twistd")

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 413, 500, 503, 504)
}


def _error(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Settings default to the environment."""
    cfg = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(
            level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        solver = get_solver(cfg.solver)
        started = time.perf_counter()
        solver.warmup()
        service = SolveService(solver, cfg)
        await service.start()
        logger.info(
            "solver ready solver=%s warmup_ms=%.1f threads=%d batching=%s cache=%d",
            solver.name,
            (time.perf_counter() - started) * 1000,
            service.threads,
            service.batching,
            cfg.cache_size,
        )
        app.state.service = service
        app.state.metrics = Metrics()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(
        title="twistd",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if cfg.docs_enabled else None,
        redoc_url="/redoc" if cfg.docs_enabled else None,
        openapi_url="/openapi.json" if cfg.docs_enabled else None,
    )
    # Order matters: the size limit runs first, and headers wrap every response.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=cfg.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(InvalidCubeError)
    async def invalid_cube_handler(request: Request, exc: InvalidCubeError) -> JSONResponse:
        request.app.state.metrics.rejected_invalid += 1
        return _error(400, str(exc))

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Report malformed bodies as 400 (not FastAPI's default 422), consistent with bad
        # cubes. Only field locations and messages are echoed back, never the input.
        request.app.state.metrics.rejected_invalid += 1
        messages = [
            f"{'.'.join(str(p) for p in err['loc'] if p != 'body') or 'body'}: {err['msg']}"
            for err in exc.errors()
        ]
        return _error(400, "; ".join(messages))

    @app.exception_handler(OverloadedError)
    async def overload_handler(request: Request, exc: OverloadedError) -> JSONResponse:
        request.app.state.metrics.rejected_overload += 1
        return _error(503, str(exc), headers={"Retry-After": "1"})

    @app.exception_handler(SolveTimeoutError)
    async def timeout_handler(request: Request, exc: SolveTimeoutError) -> JSONResponse:
        request.app.state.metrics.timeouts += 1
        return _error(504, str(exc))

    @app.exception_handler(SolverFaultError)
    async def fault_handler(request: Request, exc: SolverFaultError) -> JSONResponse:
        request.app.state.metrics.solver_faults += 1
        return _error(500, "internal solver error")

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        # Log the details server-side; never leak tracebacks to clients.
        logger.exception("unhandled error")
        return _error(500, "internal server error")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/metrics")
    def metrics(request: Request) -> dict[str, object]:
        service: SolveService = request.app.state.service
        stats: Metrics = request.app.state.metrics
        return stats.snapshot(
            batching=service.batching,
            queue_depth=service.pending,
            extra={
                "solver": {"name": service.solver.name, "threads": service.threads},
                "methods": service.method_counts,
                "cache": {
                    "size": len(service.cache),
                    "capacity": service.cache.capacity,
                    "hits": service.cache_hits,
                },
            },
        )

    @app.post("/solve", response_model=SolveResponse, responses=_ERRORS)
    async def solve(body: SolveRequest, request: Request) -> SolveResponse:
        received = time.perf_counter()
        cube = normalize(body.cube)
        validate_facelets(cube)

        service: SolveService = request.app.state.service
        result = await service.solve(cube, body.method)

        total_ms = (time.perf_counter() - received) * 1000
        steps = [
            StepOut(
                stage=s.stage,
                moves=" ".join(s.moves),
                move_count=move_count(" ".join(s.moves)),
                explanation=s.explanation,
                case=s.case,
                algorithm=s.algorithm,
            )
            for s in result.steps
        ]
        total_moves = sum(s.move_count for s in steps)
        request.app.state.metrics.record_solve(
            total_ms=total_ms,
            solve_ms=result.solve_ms,
            queue_ms=result.queue_ms,
            batch_size=result.batch_size,
        )
        logger.info(
            "solve method=%s moves=%d solve_ms=%.3f queue_ms=%.3f batch=%d cached=%s total_ms=%.3f",
            result.method,
            total_moves,
            result.solve_ms,
            result.queue_ms,
            result.batch_size,
            result.cached,
            total_ms,
        )
        return SolveResponse(
            solution=result.solution,
            move_count=total_moves,
            solver=service.solver.name if result.method == "optimal" else "twistd",
            solve_ms=round(result.solve_ms, 3),
            method=result.method,
            steps=steps,
        )

    return app


app = create_app()
