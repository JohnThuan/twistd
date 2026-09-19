"""Closed-loop load test for twistd.

Runs `--concurrency` clients that each send /solve requests back to back until
`--requests` have been sent, then prints throughput and latency percentiles.

    python -m scripts.loadtest --url http://localhost:8000 --concurrency 64 --requests 2000
    python -m scripts.loadtest --method cfop --concurrency 16 --requests 500
    python -m scripts.loadtest --distinct 50   # 50 unique cubes, repeated: exercises the cache

Latency is reported separately for successful solves and for rejections (503),
so fast load-shedding doesn't make the solve latency look better than it is.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time

import httpx

from twistd.cube import SOLVED, apply_moves, random_scramble
from twistd.metrics import percentile


def make_cubes(n: int, distinct: int, scramble_length: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    unique = [apply_moves(SOLVED, random_scramble(scramble_length, rng)) for _ in range(distinct)]
    return [unique[i % distinct] for i in range(n)]


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "mean": round(statistics.fmean(values), 2),
        "p50": round(percentile(values, 50), 2),
        "p95": round(percentile(values, 95), 2),
        "p99": round(percentile(values, 99), 2),
        "max": round(max(values), 2),
    }


async def run(
    url: str, cubes: list[str], method: str, concurrency: int, timeout_s: float
) -> dict[str, object]:
    ok_latencies: list[float] = []
    rejected_latencies: list[float] = []
    statuses: dict[int, int] = {}
    next_index = 0

    async def worker(client: httpx.AsyncClient) -> None:
        nonlocal next_index
        while next_index < len(cubes):
            cube = cubes[next_index]
            next_index += 1
            started = time.perf_counter()
            try:
                resp = await client.post("/solve", json={"cube": cube, "method": method})
                code = resp.status_code
            except httpx.HTTPError:
                code = 0  # connection error / client timeout
            elapsed_ms = (time.perf_counter() - started) * 1000
            (ok_latencies if code == 200 else rejected_latencies).append(elapsed_ms)
            statuses[code] = statuses.get(code, 0) + 1

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=url, limits=limits, timeout=timeout_s) as client:
        # Warm up connections before timing.
        await asyncio.gather(*(client.get("/health") for _ in range(concurrency)))
        before = (await client.get("/metrics")).json()
        started = time.perf_counter()
        await asyncio.gather(*(worker(client) for _ in range(concurrency)))
        elapsed = time.perf_counter() - started
        after = (await client.get("/metrics")).json()

    solved = statuses.get(200, 0)
    return {
        "method": method,
        "requests": len(cubes),
        "distinct_cubes": len(set(cubes)),
        "concurrency": concurrency,
        "elapsed_s": round(elapsed, 2),
        "solved_per_s": round(solved / elapsed, 1),
        "status_codes": dict(sorted(statuses.items())),
        "latency_ms": _summary(ok_latencies),
        "rejected_latency_ms": _summary(rejected_latencies),
        "cache_hits": after["cache"]["hits"] - before["cache"]["hits"],
        "server": {"threads": after["solver"]["threads"], "batching": after["batching"]["enabled"]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--method", default="optimal")
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--distinct", type=int, default=0, help="unique cubes (default: all)")
    parser.add_argument("--scramble-length", type=int, default=25)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="print raw JSON only")
    args = parser.parse_args()

    distinct = args.distinct or args.requests
    cubes = make_cubes(args.requests, distinct, args.scramble_length, args.seed)
    result = asyncio.run(run(args.url, cubes, args.method, args.concurrency, args.timeout))

    if args.json:
        print(json.dumps(result))
        return
    lat = result["latency_ms"]
    print(
        f"method={result['method']}  concurrency={result['concurrency']}  "
        f"requests={result['requests']} ({result['distinct_cubes']} distinct)  "
        f"statuses={result['status_codes']}\n"
        f"  solved: {result['solved_per_s']}/s over {result['elapsed_s']} s, "
        f"cache hits {result['cache_hits']}\n"
        f"  solve latency ms: {lat}\n"
        f"  rejected latency ms: {result['rejected_latency_ms']}"
    )


if __name__ == "__main__":
    main()
