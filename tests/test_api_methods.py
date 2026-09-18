import random

import pytest
from fastapi.testclient import TestClient

from twistd.cube import SOLVED, apply_moves, random_scramble
from twistd.methods.notation import to_face_turns

EXPECTED_STAGES = {
    "beginner": {"Cross", "First layer corners", "Middle layer", "Yellow cross"},
    "cfop": {"Cross", "F2L 1", "F2L 4", "OLL", "PLL"},
    "cfop-best": {"Cross", "F2L 1", "F2L 4", "OLL", "PLL"},
}


def _cube(seed: int) -> str:
    return apply_moves(SOLVED, random_scramble(25, random.Random(seed)))


def _replay(cube: str, notation: str) -> str:
    turns = " ".join(to_face_turns(notation)[0])
    return apply_moves(cube, turns) if turns else cube


@pytest.mark.parametrize("method", ["optimal", "beginner", "cfop", "cfop-best"])
def test_every_method_returns_a_solution_that_works(client: TestClient, method: str) -> None:
    cube = _cube(100)
    resp = client.post("/solve", json={"cube": cube, "method": method})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["method"] == method
    assert _replay(cube, body["solution"]) == SOLVED
    # The steps, replayed in order, are the same solution.
    assert " ".join(s["moves"] for s in body["steps"] if s["moves"]) == body["solution"]
    assert body["move_count"] == sum(s["move_count"] for s in body["steps"])


@pytest.mark.parametrize("method", ["beginner", "cfop", "cfop-best"])
def test_teaching_methods_return_named_stages(client: TestClient, method: str) -> None:
    body = client.post("/solve", json={"cube": _cube(101), "method": method}).json()
    assert EXPECTED_STAGES[method] <= {s["stage"] for s in body["steps"]}
    assert body["solver"] == "twistd"
    assert all(s["explanation"] for s in body["steps"])


def test_cfop_names_its_last_layer_cases(client: TestClient) -> None:
    body = client.post("/solve", json={"cube": _cube(102), "method": "cfop"}).json()
    oll = next(s for s in body["steps"] if s["stage"] == "OLL")
    assert oll["case"].startswith("OLL")


def test_rotations_are_not_counted_as_moves(client: TestClient) -> None:
    for seed in range(103, 110):
        body = client.post("/solve", json={"cube": _cube(seed), "method": "cfop"}).json()
        tokens = body["solution"].split()
        rotations = sum(t[0] in "xyz" for t in tokens)
        assert body["move_count"] == len(tokens) - rotations


def test_methods_are_cached_separately(client: TestClient) -> None:
    cube = _cube(111)
    optimal = client.post("/solve", json={"cube": cube, "method": "optimal"}).json()
    beginner = client.post("/solve", json={"cube": cube, "method": "beginner"}).json()
    assert optimal["solution"] != beginner["solution"]
    again = client.post("/solve", json={"cube": cube, "method": "beginner"}).json()
    assert again["solution"] == beginner["solution"]


def test_method_defaults_to_optimal(client: TestClient) -> None:
    assert client.post("/solve", json={"cube": _cube(112)}).json()["method"] == "optimal"


def test_unknown_method_rejected(client: TestClient) -> None:
    resp = client.post("/solve", json={"cube": _cube(113), "method": "roux"})
    assert resp.status_code == 400
    assert "method" in resp.json()["detail"]


def test_already_solved_cube_has_no_moves_in_any_method(client: TestClient) -> None:
    for method in ("optimal", "beginner", "cfop", "cfop-best"):
        body = client.post("/solve", json={"cube": SOLVED, "method": method}).json()
        assert body["move_count"] == 0, method


def test_metrics_count_solves_per_method(client: TestClient) -> None:
    before = client.get("/metrics").json()["methods"]["beginner"]
    client.post("/solve", json={"cube": _cube(114), "method": "beginner"})
    assert client.get("/metrics").json()["methods"]["beginner"] == before + 1
