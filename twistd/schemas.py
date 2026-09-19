from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from twistd.methods.registry import Method

EXAMPLE_CUBE = "DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD"


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cube: str = Field(
        description="54-character facelet string in kociemba order (U R F D L B).",
        examples=[EXAMPLE_CUBE],
        # 54 facelets plus slack for surrounding whitespace, which is stripped.
        max_length=128,
    )
    method: Method = Field(
        default="optimal",
        description=(
            "optimal: fewest moves. beginner: layer by layer. cfop: speedcubing method, "
            "human-friendly moves. cfop-best: CFOP with the fewest moves."
        ),
    )


class StepOut(BaseModel):
    stage: str = Field(description='Stage name, e.g. "Cross", "F2L 2", "OLL".')
    moves: str = Field(description="Moves for this step in cubing notation.")
    move_count: int = Field(description="Moves in this step; cube rotations are not counted.")
    explanation: str
    case: str | None = Field(default=None, description='Recognized case, e.g. "OLL 27 (Sune)".')
    algorithm: str | None = Field(
        default=None, description="The memorized algorithm this step uses; the rest is setup."
    )


class SolveResponse(BaseModel):
    solution: str = Field(description="All moves, space-separated; empty if already solved.")
    move_count: int = Field(description="Total moves; cube rotations are not counted.")
    solver: str
    solve_ms: float
    method: Method
    steps: list[StepOut]


class HealthResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    detail: str
