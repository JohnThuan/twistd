from fastapi.testclient import TestClient

from twistd.cube import SOLVED
from twistd.metrics import Metrics, percentile


def test_percentile_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 100) == 100
    assert percentile([], 50) == 0.0
    assert percentile([7.0], 99) == 7.0


def test_snapshot_summarizes_samples() -> None:
    m = Metrics()
    for i in range(1, 11):
        m.record_solve(total_ms=i * 10, solve_ms=i, queue_ms=0.5, batch_size=4)
    m.rejected_invalid += 2

    snap = m.snapshot(batching=True, queue_depth=3)
    assert snap["requests"] == {"solved": 10, "rejected_invalid": 2, "rejected_overload": 0}
    assert snap["latency_ms"]["total"]["p50"] == 50
    assert snap["latency_ms"]["solve"]["max"] == 10
    assert snap["batching"] == {"enabled": True, "avg_batch_size": 4.0, "queue_depth": 3}


def test_metrics_endpoint_counts_requests(client: TestClient) -> None:
    before = client.get("/metrics").json()
    client.post("/solve", json={"cube": SOLVED})
    client.post("/solve", json={"cube": "nope"})
    after = client.get("/metrics").json()

    assert after["requests"]["solved"] == before["requests"]["solved"] + 1
    assert after["requests"]["rejected_invalid"] == before["requests"]["rejected_invalid"] + 1
    assert set(after["latency_ms"]) == {"total", "solve", "queue"}
    assert after["latency_ms"]["total"]["p50"] >= 0
