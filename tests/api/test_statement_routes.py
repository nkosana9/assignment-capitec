"""API layer tests for the statement routes.

The controller is replaced with a recording fake, so these tests cover only HTTP concerns:
request parsing, authentication, status-code mapping, and response shape. Storage and token
logic are exercised by the controller and e2e tests instead.
"""

import io
from datetime import UTC, datetime

import pytest

from service.controllers import statement_controller
from service.dtos.statement_dtos import Download, IssuedLink, StoredStatement
from service.dtos.storage_dtos import ObjectInfo, ObjectStream
from service.errors import (
    LinkExpired,
    LinkInvalid,
    ObjectNotFound,
    StatementNotFound,
    StatementTooLarge,
    TtlExceedsMaximum,
)
from tests.conftest import CUSTOMER

STATEMENT_ID = "a" * 32
LINK_URL = "https://files.example.test/api/v1/statements/downloads/token-123"
EXPIRES_AT = datetime(2030, 1, 1, tzinfo=UTC)


class FakeController:
    """Stands in for the statement controller and records how the routes call it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.upload_result = StoredStatement(
            statement_id=STATEMENT_ID,
            filename="report.pdf",
            content_type="application/pdf",
            customer_id=CUSTOMER,
        )
        self.link_result = IssuedLink(url=LINK_URL, expires_at=EXPIRES_AT)
        self.link_error: Exception | None = None
        self.download_result: Download | None = None
        self.download_error: Exception | None = None
        self.upload_error: Exception | None = None

    def upload_statement(self, store, **kwargs):
        self.calls.append(("upload", kwargs))
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_result

    def create_download_link(self, store, settings, **kwargs):
        self.calls.append(("link", kwargs))
        if self.link_error is not None:
            raise self.link_error
        return self.link_result

    def get_download(self, store, settings, **kwargs):
        self.calls.append(("download", kwargs))
        if self.download_error is not None:
            raise self.download_error
        return self.download_result


@pytest.fixture
def controller(monkeypatch) -> FakeController:
    fake = FakeController()
    monkeypatch.setattr(statement_controller, "upload_statement", fake.upload_statement)
    monkeypatch.setattr(statement_controller, "create_download_link", fake.create_download_link)
    monkeypatch.setattr(statement_controller, "get_download", fake.get_download)
    return fake


def _download(chunks: list[bytes], filename: str = "report.pdf") -> Download:
    size = sum(len(c) for c in chunks)
    info = ObjectInfo(content_type="application/pdf", filename=filename, owner=CUSTOMER, size=size)
    return Download(filename=filename, stream=ObjectStream(chunks=iter(chunks), info=info))


def _upload(client, auth, **overrides):
    fields = {
        "headers": auth,
        "data": {"customer_id": CUSTOMER},
        "files": {"statement": ("report.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    }
    fields.update(overrides)
    return client.post("/api/v1/statements", **fields)


def _create_link(client, auth, body: dict | None = None, statement_id: str = STATEMENT_ID):
    payload = {"customer_id": CUSTOMER, **(body or {})}
    return client.post(f"/api/v1/statements/{statement_id}/links", headers=auth, json=payload)


# ---- upload ----------------------------------------------------------------------------------


def test_upload_returns_201_with_stored_metadata(client, auth, controller):
    resp = _upload(client, auth)

    assert resp.status_code == 201
    assert resp.json() == {
        "statement_id": STATEMENT_ID,
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "customer_id": CUSTOMER,
    }


def test_upload_passes_form_fields_to_controller(client, auth, controller):
    _upload(client, auth)

    name, kwargs = controller.calls[0]
    assert name == "upload"
    assert kwargs["customer_id"] == CUSTOMER
    assert kwargs["raw_filename"] == "report.pdf"
    assert kwargs["raw_content_type"] == "application/pdf"


def test_upload_passes_configured_size_limit_to_controller(client, auth, controller, settings):
    _upload(client, auth)

    _, kwargs = controller.calls[0]
    assert kwargs["max_bytes"] == settings.max_upload_bytes


def test_upload_over_the_limit_returns_413(client, auth, controller):
    controller.upload_error = StatementTooLarge(10)

    resp = _upload(client, auth)

    assert resp.status_code == 413
    assert resp.json()["detail"] == "Statement exceeds the maximum upload size of 10 bytes."


def test_upload_requires_api_key(client, controller):
    resp = _upload(client, {})

    assert resp.status_code == 401
    assert controller.calls == []


def test_upload_rejects_wrong_api_key(client, controller):
    resp = _upload(client, {"X-API-Key": "wrong"})

    assert resp.status_code == 401
    assert controller.calls == []


def test_upload_requires_customer_id(client, auth, controller):
    resp = _upload(client, auth, data={})

    assert resp.status_code == 422
    assert controller.calls == []


def test_upload_rejects_malformed_customer_id(client, auth, controller):
    resp = _upload(client, auth, data={"customer_id": "bad id with spaces"})

    assert resp.status_code == 422
    assert controller.calls == []


# ---- create link -----------------------------------------------------------------------------


def test_create_link_returns_url_and_expiry(client, auth, controller):
    resp = _create_link(client, auth, {"expires_in_seconds": 300})

    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == LINK_URL
    assert datetime.fromisoformat(body["expires_at"]) == EXPIRES_AT


def test_create_link_passes_path_prefix_and_request_fields(client, auth, controller):
    _create_link(client, auth, {"expires_in_seconds": 300})

    name, kwargs = controller.calls[0]
    assert name == "link"
    assert kwargs == {
        "statement_id": STATEMENT_ID,
        "customer_id": CUSTOMER,
        "expiry_in_seconds": 300,
        "path_prefix": "/api/v1/statements",
    }


def test_create_link_maps_ttl_too_long_to_400(client, auth, controller):
    controller.link_error = TtlExceedsMaximum(86400)

    resp = _create_link(client, auth, {"expires_in_seconds": 90000})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "expires_in_seconds must be at most 86400."


def test_create_link_maps_not_found_to_404(client, auth, controller):
    controller.link_error = StatementNotFound(STATEMENT_ID)

    resp = _create_link(client, auth)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "File not found."


def test_create_link_rejects_ttl_below_minimum_before_controller(client, auth, controller):
    resp = _create_link(client, auth, {"expires_in_seconds": 5})

    assert resp.status_code == 422
    assert controller.calls == []


def test_create_link_rejects_malformed_statement_id(client, auth, controller):
    resp = _create_link(client, auth, statement_id="not-a-valid-id")

    assert resp.status_code == 422
    assert controller.calls == []


def test_create_link_requires_customer_id(client, auth, controller):
    resp = client.post(f"/api/v1/statements/{STATEMENT_ID}/links", headers=auth, json={"expires_in_seconds": 300})

    assert resp.status_code == 422
    assert controller.calls == []


def test_create_link_requires_api_key(client, controller):
    resp = _create_link(client, {})

    assert resp.status_code == 401
    assert controller.calls == []


# ---- download --------------------------------------------------------------------------------


def test_download_streams_chunks_with_headers(client, controller):
    controller.download_result = _download([b"hello ", b"world"])

    resp = client.get("/api/v1/statements/downloads/token-123")

    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-length"] == "11"
    assert resp.headers["content-disposition"] == 'attachment; filename="report.pdf"'
    assert resp.headers["cache-control"] == "private, no-store"
    assert controller.calls == [("download", {"token": "token-123"})]


def test_download_maps_expired_link_to_400(client, controller):
    controller.download_error = LinkExpired()

    resp = client.get("/api/v1/statements/downloads/token-123")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "This download link has expired."


def test_download_maps_invalid_link_to_403(client, controller):
    controller.download_error = LinkInvalid()

    resp = client.get("/api/v1/statements/downloads/token-123")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Invalid download link."


def test_download_maps_missing_object_to_404(client, controller):
    controller.download_error = ObjectNotFound("gone")

    resp = client.get("/api/v1/statements/downloads/token-123")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "File no longer exists."


def test_old_download_path_is_gone(client, controller):
    assert client.get("/api/v1/statements/download/token-123").status_code == 404
