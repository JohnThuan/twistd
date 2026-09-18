# twistd

![CI](https://github.com/JohnThuan/twistd/actions/workflows/ci.yml/badge.svg)

A small HTTP service that solves Rubik's Cubes. Send it a scrambled cube, get back a solution (usually around 20 moves) in a couple of milliseconds.

Built with FastAPI and Herbert Kociemba's two-phase algorithm.

## Quick start

```bash
docker build -t twistd .
docker run --rm -p 8000:8000 twistd
```

Then solve a cube:

```bash
curl -X POST localhost:8000/solve \
  -H "content-type: application/json" \
  -d '{"cube": "DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD"}'
```

```json
{
  "solution": "D2 R' D' F2 B D R2 D2 R' F2 D' F2 U' B2 L2 U2 D R2 U",
  "move_count": 19,
  "solver": "kociemba",
  "solve_ms": 2.064
}
```

Interactive API docs are at http://localhost:8000/docs.

## API

| Method | Path      | Description                          |
|--------|-----------|--------------------------------------|
| POST   | `/solve`  | Solve a cube (body: `{"cube": "..."}`) |
| GET    | `/health` | Returns `{"status": "ok"}`           |

Bad input (wrong length, invalid characters, impossible cube states) returns a `400` with a `detail` message explaining what's wrong.

### Cube format

A cube is a 54-character string: 9 stickers for each face, in the order **U R F D L B** (up, right, front, down, left, back). Each sticker is labelled by the face whose center it matches. Each face is read row by row, as seen looking straight at it in this layout:

```
        U
    L   F   R   B
        D
```

A solved cube is `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`. Lowercase and surrounding whitespace are accepted.

## Configuration

| Env var     | Default    | Description        |
|-------------|------------|--------------------|
| `SOLVER`    | `kociemba` | Which solver to use |
| `LOG_LEVEL` | `INFO`     | Python log level   |

## Development

Run the tests in Docker (no local Python setup needed):

```bash
docker build --target test -t twistd-test .
docker run --rm twistd-test
```

Or locally with Python 3.11+:

```bash
pip install -r requirements-dev.txt
pytest
```

## Project layout

```
twistd/
  main.py          FastAPI app and routes
  cube.py          cube model: validation, moves, scrambles
  schemas.py       request/response models
  config.py        env-based settings
  solvers/         pluggable solver backends
tests/             unit and API tests
```
