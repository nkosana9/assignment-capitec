"""End-to-end flows through the full app: real routes, real controller, in-memory store.

API-level concerns (validation, auth, status-code mapping) are covered in tests/api/.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from service.libs.security import issue_download_token, verify_download_token
from tests.conftest import CUSTOMER, SIGNING_KEY, FakeStore, upload


def create_link(client: TestClient, auth: dict, statement_id: str, body: dict | None = None, customer=CUSTOMER):
    payload = {"customer_id": customer, **(body or {})}
    return client.post(f"/api/v1/statements/{statement_id}/links", headers=auth, json=payload)


def token_from(url: str) -> str:
    return url.rsplit("/downloads/", 1)[1]


def test_upload_link_download_round_trip(client, auth):
    statement_id = upload(client, auth, name="../evil name?.pdf", data=b"hello world")

    link = create_link(client, auth, statement_id, {"expires_in_seconds": 300})
    assert link.status_code == 200, link.text
    url = link.json()["url"]
    assert url.startswith("https://files.example.test/api/v1/statements/downloads/")

    resp = client.get(url.removeprefix("https://files.example.test"))
    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'attachment; filename="evil_name_.pdf"'
    assert resp.headers["cache-control"] == "private, no-store"


def test_expires_at_matches_requested_ttl(client, auth):
    statement_id = upload(client, auth)
    before = datetime.now(UTC)

    resp = create_link(client, auth, statement_id, {"expires_in_seconds": 600})

    expires_at = datetime.fromisoformat(resp.json()["expires_at"])
    assert timedelta(seconds=599) < expires_at - before <= timedelta(seconds=601)


def test_default_ttl_used_when_expires_not_given(client, auth, settings):
    statement_id = upload(client, auth)
    before = datetime.now(UTC)

    resp = create_link(client, auth, statement_id)

    expires_at = datetime.fromisoformat(resp.json()["expires_at"])
    expected = timedelta(seconds=settings.link_default_ttl_seconds)
    assert expected - timedelta(seconds=2) < expires_at - before <= expected + timedelta(seconds=2)


def test_expired_link_is_rejected(client, auth):
    statement_id = upload(client, auth)
    expired, _ = issue_download_token(
        object_key=statement_id, filename="report.pdf", owner=CUSTOMER, signing_key=SIGNING_KEY, ttl_seconds=-5
    )

    assert client.get(f"/api/v1/statements/downloads/{expired}").status_code == 400


def test_link_signed_with_other_key_is_rejected(client, auth):
    statement_id = upload(client, auth)
    forged, _ = issue_download_token(
        object_key=statement_id, filename="report.pdf", owner=CUSTOMER, signing_key="x" * 40, ttl_seconds=300
    )

    assert client.get(f"/api/v1/statements/downloads/{forged}").status_code == 403


def test_tampered_token_is_rejected(client, auth):
    statement_id = upload(client, auth)
    url = create_link(client, auth, statement_id).json()["url"]
    token = token_from(url)
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")

    assert client.get(f"/api/v1/statements/downloads/{tampered}").status_code == 403


def test_link_for_deleted_object_returns_404(client, auth, store: FakeStore):
    statement_id = upload(client, auth)
    url = create_link(client, auth, statement_id).json()["url"]
    del store.objects[statement_id]

    assert client.get(url.replace("https://files.example.test", "")).status_code == 404


def test_link_for_another_customers_file_is_refused(client, auth, store: FakeStore):
    statement_id = upload(client, auth, customer="cust-A")

    resp = create_link(client, auth, statement_id, customer="cust-B")

    assert resp.status_code == 404
    assert "url" not in resp.json()
    assert store.objects[statement_id].owner == "cust-A"


def test_other_customer_and_unknown_statement_get_identical_responses(client, auth):
    # Responses must not reveal whether a statement ID exists.
    statement_id = upload(client, auth, customer="cust-A")

    other = create_link(client, auth, statement_id, customer="cust-B")
    unknown = create_link(client, auth, "0" * 32, customer="cust-B")

    assert other.status_code == unknown.status_code == 404
    assert other.json() == unknown.json()


def test_token_carries_owner_claim(client, auth):
    statement_id = upload(client, auth, customer="cust-A")
    url = create_link(client, auth, statement_id, customer="cust-A").json()["url"]

    claims = verify_download_token(token_from(url), SIGNING_KEY)

    assert claims["sub"] == statement_id
    assert claims["own"] == "cust-A"
