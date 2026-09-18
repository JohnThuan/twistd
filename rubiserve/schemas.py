from __future__ import annotations

from pydantic import BaseModel, Field

EXAMPLE_CUBE = "DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD"


class SolveRequest(BaseModel):
    cube: str = Field(
        description="54-character facelet string in kociemba order (U R F D L B).",
        examples=[EXAMPLE_CUBE],
    )


class SolveResponse(BaseModel):
    solution: str = Field(description="Space-separated moves; empty if already solved.")
    move_count: int
    solver: str
    solve_ms: float


class HealthResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    detail: str
