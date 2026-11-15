"""API layer tests for the health endpoints. Only the storage dependency is faked."""

from tests.conftest import FakeStore


def test_livez_is_public(client):
    resp = client.get("/livez")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_livez_ignores_storage_outage(client, store: FakeStore):
    store.reachable = False

    assert client.get("/livez").status_code == 200


def test_readyz_reports_ready_when_storage_is_reachable(client):
    resp = client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"storage": "ok"}}


def test_readyz_returns_503_when_storage_is_unreachable(client, store: FakeStore):
    store.reachable = False

    resp = client.get("/readyz")

    assert resp.status_code == 503
    # The response names the failing check but not the underlying error.
    assert resp.json() == {"status": "unavailable", "checks": {"storage": "unreachable"}}


def test_healthz_is_removed(client):
    assert client.get("/healthz").status_code == 404
