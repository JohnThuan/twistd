"""The beginner (layer-by-layer) method, done the way it's taught.

Unlike CFOP there's no search for short solutions: each stage follows the
recipe a first-time solver learns ("hold it here, repeat R U R' U' until..."),
so every step can be explained. The solver works on the cube *as the user
holds it*: after a `y` rotation, "the front" means the new front.

Stages: cross, first-layer corners, middle-layer edges, yellow cross, yellow
edges, yellow corner positions, yellow corner twists.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from twistd.cube import SOLVED, apply_moves
from twistd.methods.cfop import CROSS, Step
from twistd.methods.notation import simplify, to_face_turns
from twistd.methods.pieces import home, locate, slot_of, view_after_y
from twistd.methods.search import ida_star, table_for

SEXY: Final = "R U R' U'"
RIGHT_INSERT: Final = "U R U' R' U' F' U F"  # edge at UF, front sticker matches F
RIGHT_INSERT_FROM_SIDE: Final = "U' F' U F U R U' R'"  # edge at UR, side sticker matches R
YELLOW_CROSS: Final = "F R U R' U' F'"
SUNE: Final = "R U R' U R U2 R'"
CORNER_CYCLE: Final = "U R U' L' U R' U' L"
CORNER_TWIST: Final = "R' D' R D"

_Y_TOKENS: Final = {"y": 1, "y2": 2, "y'": 3}
MIDDLE_EDGES: Final = ("FR", "FL", "BR", "BL")
TOP_CORNERS: Final = ("UFR", "UFL", "UBR", "UBL")
TOP_EDGES: Final = ("UF", "UR", "UB", "UL")


class _Session:
    """A cube in the user's hands: rotations re-orient it, turns turn it."""

    def __init__(self, cube: str) -> None:
        self.cube = cube
        self.steps: list[Step] = []
        self._moves: list[str] = []
        self._setup: list[str] = []

    def _play(self, token: str) -> None:
        if token in _Y_TOKENS:
            self.cube = view_after_y(self.cube, _Y_TOKENS[token])
        else:
            self.cube = apply_moves(self.cube, token)

    def turn(self, token: str) -> None:
        """A setup move (U to line something up, y to reposition). Consecutive
        setup moves are merged for display: U U U reads as U'."""
        if token:
            self._play(token)
            self._setup.append(token)

    def do(self, algorithm: str) -> None:
        """An algorithm the learner memorizes: shown exactly as written."""
        self._flush_setup()
        for token in algorithm.split():
            self._play(token)
            self._moves.append(token)

    def _flush_setup(self) -> None:
        self._moves.extend(simplify(self._setup))
        self._setup = []

    def step(
        self, stage: str, explanation: str, case: str | None = None, algorithm: str | None = None
    ) -> None:
        """Close the current step: everything done since the last step belongs to it."""
        self._flush_setup()
        self.steps.append(Step(stage, tuple(self._moves), explanation, case, algorithm))
        self._moves = []

    def solved(self, piece: str) -> bool:
        return locate(self.cube, piece) == home(piece)

    def placed(self, piece: str) -> bool:
        """In its slot, twisted or not."""
        return slot_of(locate(self.cube, piece)) == slot_of(home(piece))


def _rotation_to_front_right(slot: str) -> str:
    """The y turn that brings a D-layer corner slot or middle edge slot to front-right."""
    for token, target in (("", "FR"), ("y'", "FL"), ("y", "BR"), ("y2", "BL")):
        if slot.endswith(target) or slot[1:] == target:
            return token
    raise ValueError(slot)


# --- 1. cross -----------------------------------------------------------------
def _cross(s: _Session) -> None:
    done: tuple[str, ...] = ()
    for edge in CROSS:
        pieces = (*done, edge)
        table = table_for(pieces)
        moves = ida_star(tuple(locate(s.cube, p) for p in pieces), table.distance, max_depth=8)
        if moves is None:  # every cross edge is solvable within 8 moves
            raise RuntimeError(f"no solution for cross edge {edge}")
        s.do(" ".join(moves))
        done = pieces
        s.step("Cross", f"Bring the {edge} edge down so both its colors match their centers.", edge)


# --- 2. first layer corners ------------------------------------------------------
def _first_layer_corners(s: _Session) -> None:
    for _ in range(4):
        todo = [c for c in ("DFR", "DFL", "DBR", "DBL") if not s.solved(c)]
        if not todo:
            break
        # Prefer a corner already waiting in the top layer: no need to pop one out.
        waiting = [c for c in todo if slot_of(locate(s.cube, c)) in _TOP_CORNER_SLOTS]
        target = (waiting or todo)[0]
        s.turn(_rotation_to_front_right(target))  # now the target belongs at DFR

        # Stuck in another bottom slot: pop it into the top layer first.
        where = slot_of(locate(s.cube, "DFR"))
        if where not in _TOP_CORNER_SLOTS and where != slot_of(home("DFR")):
            pop = _rotation_to_front_right(_slot_name(where))
            back = {"": "", "y": "y'", "y'": "y", "y2": "y2"}[pop]
            s.turn(pop)
            s.do(SEXY)
            s.turn(back)
        # Turn the top until it sits right above its slot.
        for _ in range(4):
            if slot_of(locate(s.cube, "DFR")) in (slot_of(home("UFR")), slot_of(home("DFR"))):
                break
            s.turn("U")
        # Repeat the trigger until it drops in the right way round (at most 5 times).
        for _ in range(6):
            if s.solved("DFR"):
                break
            s.do(SEXY)
        s.step(
            "First layer corners",
            f"Put the corner above its slot, then repeat {SEXY} until it's solved.",
            "corner",
            SEXY,
        )


# --- 3. middle layer edges -------------------------------------------------------
def _in_top(s: _Session, piece: str) -> bool:
    return slot_of(locate(s.cube, piece)) in _TOP_EDGE_SLOTS


def _middle_edges(s: _Session) -> None:
    for _ in range(8):
        todo = [e for e in MIDDLE_EDGES if not s.solved(e)]
        if not todo:
            break
        waiting = [e for e in todo if _in_top(s, e)]
        if not waiting:
            # Every missing edge is stuck in a wrong slot or flipped: pop one out.
            s.turn(_rotation_to_front_right(todo[0]))
            s.do(RIGHT_INSERT)
            s.step(
                "Middle layer",
                "Pop the stuck edge out to the top layer.",
                "stuck edge",
                RIGHT_INSERT,
            )
            continue
        s.turn(_rotation_to_front_right(waiting[0]))  # now the edge belongs at FR
        # Turn the top so the edge's side color lines up with its center.
        used = None
        for _ in range(4):
            if s.cube[19] == "F" and slot_of(locate(s.cube, "FR")) == slot_of(home("UF")):
                used = RIGHT_INSERT
                break
            if s.cube[10] == "R" and slot_of(locate(s.cube, "FR")) == slot_of(home("UR")):
                used = RIGHT_INSERT_FROM_SIDE
                break
            s.turn("U")
        if used is None:  # four U turns always bring a top-layer edge into one of the two spots
            raise RuntimeError("could not line up the middle-layer edge")
        s.do(used)
        s.step("Middle layer", "Line the edge up with its center, then insert it.", "edge", used)


# --- 4-7. last layer ----------------------------------------------------------------
def _top_edges_oriented(cube: str) -> int:
    return sum(cube[i] == "U" for i in (1, 3, 5, 7))


def _yellow_cross(s: _Session) -> None:
    for _ in range(4):
        if _top_edges_oriented(s.cube) == 4:
            break
        up = {i for i in (1, 3, 5, 7) if s.cube[i] == "U"}
        if up == {1, 7} or up == {3, 5}:  # a line: hold it left-right
            if up == {1, 7}:
                s.turn("U")
            case = "line"
        elif up:  # an L: hold it at back-left
            for _ in range(4):
                if {s.cube[1], s.cube[3]} == {"U"}:
                    break
                s.turn("U")
            case = "L-shape"
        else:
            case = "dot"
        s.do(YELLOW_CROSS)
        s.step("Yellow cross", f"Yellow {case} on top: do {YELLOW_CROSS}.", case, YELLOW_CROSS)


def _matched_edges(cube: str) -> int:
    return sum(cube[i] == cube[i + 3] for i in (10, 19, 37, 46))  # side sticker vs its center


def _best_auf(cube: str, score: Callable[[str], int]) -> str:
    return max(("", "U", "U2", "U'"), key=lambda u: score(apply_moves(cube, u) if u else cube))


def _yellow_edges(s: _Session) -> None:
    for _ in range(4):
        for token in _best_auf(s.cube, _matched_edges).split():
            s.turn(token)
        if _matched_edges(s.cube) == 4:
            break
        # Two adjacent matched edges go at the back and right; Sune + U swaps the other two.
        # Turn the whole cube (y), not the top: turning the top would unmatch them.
        for rotation in ("", "y", "y2", "y'"):
            probe = view_after_y(s.cube, _Y_TOKENS.get(rotation, 0))
            if probe[46] == probe[49] and probe[10] == probe[13]:
                s.turn(rotation)
                break
        s.do(SUNE)
        s.turn("U")
        s.step(
            "Yellow edges", f"Match the yellow edges to their centers with {SUNE}.", "edges", SUNE
        )
    if s._moves or s._setup:
        s.step("Yellow edges", "Turn the top so every yellow edge matches its center.", "align")


def _yellow_corners_placed(s: _Session) -> int:
    return sum(s.placed(c) for c in TOP_CORNERS)


def _place_corners(s: _Session) -> None:
    for _ in range(4):
        if _yellow_corners_placed(s) == 4:
            break
        # Hold a corner that's already in the right spot at front-right, then cycle the rest.
        for rotation in ("", "y", "y2", "y'"):
            probe = view_after_y(s.cube, _Y_TOKENS.get(rotation, 0))
            if slot_of(locate(probe, "UFR")) == slot_of(home("UFR")):
                s.turn(rotation)
                break
        s.do(CORNER_CYCLE)
        s.step(
            "Place yellow corners",
            f"Cycle the corners into place with {CORNER_CYCLE}.",
            "position",
            CORNER_CYCLE,
        )


def _twist_corners(s: _Session) -> None:
    for _ in range(4):
        if s.cube[8] != "U":
            # 2 or 4 repetitions twist it up. The bottom looks scrambled meanwhile;
            # it comes back once every corner is done.
            while s.cube[8] != "U":
                s.do(CORNER_TWIST)
            s.step(
                "Twist yellow corners",
                f"Repeat {CORNER_TWIST} until yellow faces up. Don't turn the cube; "
                "the bottom fixes itself at the end.",
                "twist",
                CORNER_TWIST,
            )
        if all(s.cube[i] == "U" for i in (0, 2, 6, 8)):
            break
        s.turn("U")  # bring the next corner to front-right: turn only the top layer
    for _ in range(4):
        if s.cube == SOLVED:
            break
        s.turn("U")
    if s._setup:
        s.step("Twist yellow corners", "Turn the top layer to finish the cube.", "finish")


def solve(cube: str) -> list[Step]:
    s = _Session(cube)
    _cross(s)
    _first_layer_corners(s)
    _middle_edges(s)
    _yellow_cross(s)
    _yellow_edges(s)
    _place_corners(s)
    _twist_corners(s)
    if s.cube != SOLVED:
        raise RuntimeError("beginner method did not finish the cube")

    steps = [step for step in s.steps if step.moves]
    alg = " ".join(" ".join(step.moves) for step in steps)
    if apply_moves(cube, " ".join(to_face_turns(alg)[0])) != SOLVED:
        raise RuntimeError("beginner solution does not solve the original cube")
    return steps


_TOP_CORNER_SLOTS: Final = {slot_of(home(c)) for c in TOP_CORNERS}
_TOP_EDGE_SLOTS: Final = {slot_of(home(e)) for e in TOP_EDGES}


def _slot_name(slot: tuple[int, ...]) -> str:
    for corner in ("DFR", "DFL", "DBR", "DBL", *TOP_CORNERS):
        if slot_of(home(corner)) == slot:
            return corner
    raise ValueError(slot)
