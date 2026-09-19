# twistd

![CI](https://github.com/JohnThuan/twistd/actions/workflows/ci.yml/badge.svg)

A Rubik's Cube solving service that teaches. Send it a scrambled cube and pick a method: get the shortest solution, or a step-by-step solve in the beginner method or CFOP (the speedcubing method), with every stage named and explained.

Built with FastAPI. The shortest solutions come from Herbert Kociemba's two-phase algorithm; the teaching methods run on twistd's own search engine (numpy-built distance tables + IDA\* search). Every solution is replayed and checked before it's returned.

## Quick start

```bash
docker build -t twistd .
docker run --rm -p 8000:8000 twistd
```

Then solve a cube with CFOP:

```bash
curl -X POST localhost:8000/solve \
  -H "content-type: application/json" \
  -d '{"cube": "DRLUUBFBRBLURRLRUBLRDDFDLFUFUFFDBRDUBRUFLLFDDBFLUBLRBD", "method": "cfop"}'
```

```json
{
  "solution": "R' L' F' L2 L F2 L' F U2 F U L' U' L ... R U2 R' U2 R U2",
  "move_count": 55,
  "solver": "twistd",
  "solve_ms": 61.9,
  "method": "cfop",
  "steps": [
    {
      "stage": "Cross",
      "moves": "R' L' F' L2",
      "move_count": 4,
      "explanation": "Solve the four D-layer edges so they match their centers.",
      "case": null,
      "algorithm": null
    },
    ...
    {
      "stage": "OLL",
      "moves": "R' U' F U R U' R' F' R",
      "move_count": 9,
      "explanation": "Make the whole top face one color.",
      "case": "OLL 31 (Couch)",
      "algorithm": "R' U' F U R U' R' F' R"
    },
    ...
  ]
}
```

Interactive API docs are at http://localhost:8000/docs.

### Methods

| `method` | What you get | Example cube | Typical time |
|---|---|---|---|
| `optimal` (default) | Fewest moves, one block. Fast, but not learnable. | 19 moves | ~2 ms |
| `beginner` | Layer by layer in 7 stages, using the algorithms beginners learn first | 129 moves | ~2 ms |
| `cfop` | The speedcubing method as people do it: U/R/L/F turns plus cube rotations; OLL/PLL cases named | 55 moves | ~30–60 ms |
| `cfop-best` | CFOP with the fewest moves: best of all 24 F2L orders, any face turns | 53 moves | ~350–650 ms |

`move_count` doesn't count cube rotations (`x`, `y`, `z`), the way cubers count. Each step's `algorithm` is the part to memorize; the rest of its `moves` is setup.

## API

| Method | Path | Description |
|---|---|---|
| POST | `/solve` | Solve a cube (body: `{"cube": "...", "method": "..."}`) |
| GET | `/health` | Returns `{"status": "ok"}` |
| GET | `/metrics` | Latency percentiles, throughput, cache hits, solves per method |

Errors come back as JSON with a `detail` message:

| Status | When |
|---|---|
| 400 | Wrong length, invalid characters, impossible cube state, unknown method |
| 413 | Request body over 1 KB |
| 503 | Server at capacity (retry after the `Retry-After` header) |
| 504 | A solve took longer than the timeout |

### Cube format

A cube is a 54-character string: 9 stickers for each face, in the order **U R F D L B** (up, right, front, down, left, back). Each sticker is labelled by the face whose center it matches. Each face is read row by row, as seen looking straight at it in this layout:

```
        U
    L   F   R   B
        D
```

A solved cube is `UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`. Lowercase and surrounding whitespace are accepted.

## Configuration

| Env var | Default | Description |
|---|---|---|
| `SOLVER` | `kociemba` | Solver for `optimal` |
| `SOLVER_THREADS` | usable CPUs | Threads for `optimal` (the C solver releases the GIL) |
| `METHOD_WORKERS` | min(CPUs, 4) | Worker processes for the teaching methods; 0 runs them on threads |
| `MAX_PENDING` | `512` | Solves in flight before new ones get 503 |
| `SOLVE_TIMEOUT_S` | `10` | Per-solve time limit |
| `CACHE_SIZE` | `10000` | Solutions kept in the LRU cache; 0 disables it |
| `BATCHING` | `auto` | Batch requests: `auto` (only for solvers that vectorize), `on`, `off` |
| `DOCS_ENABLED` | `true` | Serve `/docs` and `/openapi.json` |
| `LOG_LEVEL` | `INFO` | Python log level |

"Usable CPUs" respects container CPU limits (cgroups), not just the host's core count.

## Development

Run the tests in Docker (no local Python setup needed):

```bash
docker build --target test -t twistd-test .
docker run --rm twistd-test
```

Or locally with Python 3.11+:

```bash
pip install -r requirements-dev.txt -c constraints.txt
pytest
```

## Project layout

```
twistd/
  main.py          FastAPI app, routes, error mapping
  service.py       solve pipeline: cache, admission control, timeouts, verification
  batching.py      request batching for solvers that vectorize
  middleware.py    body size limit, security headers
  metrics.py       rolling latency percentiles
  schemas.py       request/response models
  config.py        env-based settings, container-aware CPU detection
  cube.py          cube model: validation, moves, scrambles
  solvers/         Kociemba backend for `optimal`
  methods/         teaching engine
    search.py      distance tables (numpy BFS) + IDA* search
    pieces.py      piece tracking, rotated views
    notation.py    wide moves, slices and rotations -> face turns
    cfop.py        cross, F2L (fixed / best / human-friendly), full CFOP
    last_layer.py  OLL (57) and PLL (21) recognition
    beginner.py    7-stage layer-by-layer method
    registry.py    method list + worker warmup
tests/             unit, API and correctness tests
scripts/           load test, dependency lock
```

## License

twistd is released under the [MIT License](LICENSE).

It depends on [kociemba](https://github.com/muodov/kociemba), which is licensed under **GPLv2**. Running twistd as a network service is unaffected, but a distributed Docker image bundles kociemba, and that bundle is subject to GPLv2's terms. All other runtime dependencies use permissive licenses (MIT, BSD, Apache-2.0, MPL-2.0).

Rubik's Cube® is a registered trademark of its owner. twistd is an independent project and is not affiliated with or endorsed by the trademark owner; the name is used only to describe what the software does.
