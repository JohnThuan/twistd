"""Closed-loop load test for twistd.

Runs `--concurrency` clients that each send /solve requests back to back until
`--requests` have been sent, then prints throughput and latency percentiles.

    python -m scripts.loadtest --url http://localhost:8000 --concurrency 64 --requests 2000
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


def make_cubes(n: int, scramble_length: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [apply_moves(SOLVED, random_scramble(scramble_length, rng)) for _ in range(n)]


async def run(url: str, cubes: list[str], concurrency: int, timeout_s: float) -> dict[str, object]:
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    next_index = 0

    async def worker(client: httpx.AsyncClient) -> None:
        nonlocal next_index
        while next_index < len(cubes):
            cube = cubes[next_index]
            next_index += 1
            started = time.perf_counter()
            try:
                resp = await client.post("/solve", json={"cube": cube})
                code = resp.status_code
            except httpx.HTTPError:
                code = 0  # connection error / timeout
            latencies.append((time.perf_counter() - started) * 1000)
            statuses[code] = statuses.get(code, 0) + 1

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=url, limits=limits, timeout=timeout_s) as client:
        # Warm up connections and the server before timing.
        await asyncio.gather(*(client.get("/health") for _ in range(concurrency)))
        started = time.perf_counter()
        await asyncio.gather(*(worker(client) for _ in range(concurrency)))
        elapsed = time.perf_counter() - started
        server_metrics = (await client.get("/metrics")).json()

    return {
        "requests": len(cubes),
        "concurrency": concurrency,
        "elapsed_s": round(elapsed, 2),
        "throughput_rps": round(len(cubes) / elapsed, 1),
        "status_codes": dict(sorted(statuses.items())),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2),
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
            "max": round(max(latencies), 2),
        },
        "server_avg_batch_size": server_metrics["batching"]["avg_batch_size"],
        "server_batching": server_metrics["batching"]["enabled"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--scramble-length", type=int, default=25)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="print raw JSON only")
    args = parser.parse_args()

    cubes = make_cubes(args.requests, args.scramble_length, args.seed)
    result = asyncio.run(run(args.url, cubes, args.concurrency, args.timeout))

    if args.json:
        print(json.dumps(result))
        return
    lat = result["latency_ms"]
    print(
        f"batching={result['server_batching']}  concurrency={result['concurrency']}  "
        f"requests={result['requests']}  statuses={result['status_codes']}\n"
        f"  throughput: {result['throughput_rps']} req/s over {result['elapsed_s']} s\n"
        f"  latency ms: p50={lat['p50']}  p95={lat['p95']}  p99={lat['p99']}  "
        f"max={lat['max']}\n"
        f"  avg batch size (server): {result['server_avg_batch_size']}"
    )


if __name__ == "__main__":
    main()
