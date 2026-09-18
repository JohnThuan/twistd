from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from rubiserve.main import app


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    # Context manager runs the lifespan, so the solver is loaded exactly as in production.
    with TestClient(app) as c:
        yield c
