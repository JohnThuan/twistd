from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from twistd import __version__
from twistd.config import Settings
from twistd.cube import InvalidCubeError, normalize, validate_facelets
from twistd.schemas import ErrorResponse, HealthResponse, SolveRequest, SolveResponse
from twistd.solvers import Solver, get_solver

logger = logging.getLogger("twistd")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    solver = get_solver(settings.solver)
    started = time.perf_counter()
    solver.warmup()
    logger.info(
        "solver ready solver=%s warmup_ms=%.1f",
        solver.name,
        (time.perf_counter() - started) * 1000,
    )
    app.state.solver = solver
    yield


app = FastAPI(title="twistd", version=__version__, lifespan=lifespan)

_BAD_REQUEST = {400: {"model": ErrorResponse}}


@app.exception_handler(InvalidCubeError)
async def invalid_cube_handler(_: Request, exc: InvalidCubeError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Report malformed bodies as 400 (not FastAPI's default 422), consistent with bad cubes.
    messages = [
        f"{'.'.join(str(p) for p in err['loc'] if p != 'body') or 'body'}: {err['msg']}"
        for err in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"detail": "; ".join(messages)})


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# Sync handler: the solver is CPU-bound, so FastAPI runs it in its threadpool
# instead of blocking the event loop.
@app.post("/solve", response_model=SolveResponse, responses=_BAD_REQUEST)
def solve(body: SolveRequest, request: Request) -> SolveResponse:
    cube = normalize(body.cube)
    validate_facelets(cube)

    solver: Solver = request.app.state.solver
    started = time.perf_counter()
    solution = solver.solve(cube)
    solve_ms = round((time.perf_counter() - started) * 1000, 3)

    move_count = len(solution.split())
    logger.info("solve solver=%s moves=%d solve_ms=%.3f", solver.name, move_count, solve_ms)
    return SolveResponse(
        solution=solution, move_count=move_count, solver=solver.name, solve_ms=solve_ms
    )
