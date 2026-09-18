import random

import pytest

from twistd.cube import (
    MOVES,
    SOLVED,
    InvalidMoveError,
    MalformedCubeError,
    apply_moves,
    invert_moves,
    random_scramble,
    validate_facelets,
)


@pytest.mark.parametrize("face", "URFDLB")
def test_quarter_turn_has_order_four(face: str) -> None:
    assert apply_moves(SOLVED, f"{face} {face} {face} {face}") == SOLVED
    assert apply_moves(SOLVED, face) != SOLVED


@pytest.mark.parametrize("face", "URFDLB")
def test_prime_and_double_are_consistent(face: str) -> None:
    assert apply_moves(SOLVED, f"{face} {face}'") == SOLVED
    assert apply_moves(SOLVED, f"{face}2") == apply_moves(SOLVED, f"{face} {face}")


def test_sexy_move_has_order_six() -> None:
    state = SOLVED
    for i in range(1, 7):
        state = apply_moves(state, "R U R' U'")
        assert (state == SOLVED) == (i == 6)


def test_u_turn_cycles_side_top_rows() -> None:
    # U clockwise (viewed from above): F's top row receives R's colors, R gets B's, etc.
    state = apply_moves(SOLVED, "U")
    assert state[18:21] == "RRR"  # F top row
    assert state[9:12] == "BBB"  # R top row
    assert state[45:48] == "LLL"  # B top row
    assert state[36:39] == "FFF"  # L top row
    assert state[0:9] == "U" * 9


def test_r_turn_brings_front_to_up() -> None:
    state = apply_moves(SOLVED, "R")
    assert [state[i] for i in (2, 5, 8)] == ["F", "F", "F"]  # U right column


def test_scramble_then_inverse_is_identity() -> None:
    rng = random.Random(0)
    for _ in range(20):
        scramble = random_scramble(30, rng)
        scrambled = apply_moves(SOLVED, scramble)
        validate_facelets(scrambled)
        assert apply_moves(scrambled, invert_moves(scramble)) == SOLVED


def test_all_18_moves_exist() -> None:
    assert len(MOVES) == 18


def test_unknown_move_rejected() -> None:
    with pytest.raises(InvalidMoveError):
        apply_moves(SOLVED, "R X")


@pytest.mark.parametrize(
    ("cube", "message"),
    [
        (SOLVED[:-1], "54 characters"),
        (SOLVED[:-1] + "X", "invalid facelet characters"),
        ("U" * 10 + SOLVED[10:], "exactly 9 times"),
        (SOLVED.replace("U", "#").replace("R", "U").replace("#", "R"), "center stickers"),
    ],
)
def test_validate_facelets_rejects(cube: str, message: str) -> None:
    with pytest.raises(MalformedCubeError, match=message):
        validate_facelets(cube)
