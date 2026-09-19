import random

import pytest
from fastapi.testclient import TestClient

from twistd.cube import SOLVED, apply_moves, random_scramble

README_CUBE = "DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD"


def _flip_uf_edge(cube: str) -> str:
    # U8 (index 7) and F2 (index 19) are the two stickers of the UF edge.
    chars = list(cube)
    chars[7], chars[19] = chars[19], chars[7]
    return "".join(chars)


def _twist_urf_corner(cube: str) -> str:
    # U9, R1, F3 (indices 8, 9, 20) are the URF corner; rotate its stickers in place.
    chars = list(cube)
    chars[8], chars[9], chars[20] = chars[20], chars[8], chars[9]
    return "".join(chars)


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_solve_valid_cube(client: TestClient) -> None:
    resp = client.post("/solve", json={"cube": README_CUBE})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"solution", "move_count", "solver", "solve_ms", "method", "steps"}
    assert body["method"] == "optimal"
    assert body["solver"] == "kociemba"
    assert body["move_count"] == len(body["solution"].split()) > 0
    assert body["solve_ms"] >= 0
    assert apply_moves(README_CUBE, body["solution"]) == SOLVED


def test_solutions_actually_solve_random_scrambles(client: TestClient) -> None:
    rng = random.Random(1234)
    for _ in range(25):
        cube = apply_moves(SOLVED, random_scramble(25, rng))
        resp = client.post("/solve", json={"cube": cube})
        assert resp.status_code == 200, resp.text
        assert apply_moves(cube, resp.json()["solution"]) == SOLVED


def test_already_solved_cube(client: TestClient) -> None:
    resp = client.post("/solve", json={"cube": SOLVED})
    assert resp.status_code == 200
    body = resp.json()
    assert body["solution"] == ""
    assert body["move_count"] == 0


def test_input_is_normalized(client: TestClient) -> None:
    resp = client.post("/solve", json={"cube": f"  {README_CUBE.lower()}\n"})
    assert resp.status_code == 200
    assert apply_moves(README_CUBE, resp.json()["solution"]) == SOLVED


@pytest.mark.parametrize(
    ("cube", "message"),
    [
        ("", "54 characters"),
        (README_CUBE[:-1], "54 characters"),
        (README_CUBE + "U", "54 characters"),
        (README_CUBE[:-1] + "X", "invalid facelet characters"),
        ("U" * 10 + SOLVED[10:], "exactly 9 times"),
        (SOLVED.replace("U", "#").replace("R", "U").replace("#", "R"), "center stickers"),
    ],
)
def test_malformed_cube_rejected(client: TestClient, cube: str, message: str) -> None:
    resp = client.post("/solve", json={"cube": cube})
    assert resp.status_code == 400
    assert message in resp.json()["detail"]


@pytest.mark.parametrize("mutate", [_flip_uf_edge, _twist_urf_corner])
def test_unsolvable_cube_rejected(client: TestClient, mutate) -> None:
    resp = client.post("/solve", json={"cube": mutate(README_CUBE)})
    assert resp.status_code == 400
    assert "not solvable" in resp.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [{}, {"cube": 123}, {"cube": None}, {"state": SOLVED}],
)
def test_bad_request_body_rejected(client: TestClient, payload: dict) -> None:
    resp = client.post("/solve", json=payload)
    assert resp.status_code == 400
    assert "cube" in resp.json()["detail"]


def test_non_json_body_rejected(client: TestClient) -> None:
    resp = client.post("/solve", content=b"not json", headers={"content-type": "application/json"})
    assert resp.status_code == 400
