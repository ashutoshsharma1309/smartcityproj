"""Health endpoint behaviour."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_liveness_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "UrbanPulse"
    assert body["environment"] == "test"
    assert body["version"]
    assert body["checked_at"]


def test_liveness_does_not_touch_the_database(client: TestClient) -> None:
    """The session fixture yields None, so any DB access would raise.

    A liveness probe that depends on the database causes orchestrators to
    restart a healthy process whenever the database blips.
    """
    assert client.get("/health").status_code == 200


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["X-Request-ID"]


def test_request_id_is_echoed_when_supplied(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["X-Request-ID"] == "trace-abc-123"


@pytest.mark.parametrize("path", ["/health/db", "/health/ready"])
def test_dependency_probes_report_failure_without_raising(client: TestClient, path: str) -> None:
    """A probe must return 200 and describe the failure, not return 500.

    Returning an error status would make the probe itself indistinguishable
    from the outage it is meant to report.
    """
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded", "unavailable"}


def test_db_probe_checks_postgis_separately(client: TestClient) -> None:
    body = client.get("/health/db").json()
    assert set(body["database"]) >= {"name", "state"}
    assert body["postgis"]["name"] == "postgis"


def test_readiness_marks_disabled_cache_as_disabled(client: TestClient) -> None:
    """Redis off by configuration is `disabled`, which is not a failure."""
    dependencies = {dep["name"]: dep for dep in client.get("/health/ready").json()["dependencies"]}
    assert dependencies["redis"]["state"] == "disabled"
