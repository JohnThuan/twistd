from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from twistd.config import Settings
from twistd.main import create_app


@pytest.fixture(scope="session", params=["on", "off"], ids=["batched", "unbatched"])
def client(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    # Every API test runs against both serving paths. The context manager runs the
    # lifespan, so the solver (and batcher) are set up exactly as in production.
    # Two real worker processes, so the teaching methods go through the process pool.
    app = create_app(Settings(batching=request.param, method_workers=2))
    with TestClient(app) as c:
        yield c
