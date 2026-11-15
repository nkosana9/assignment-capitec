"""Controller layer tests: business rules, run against the in-memory store and no HTTP."""

import io
import re
from datetime import UTC, datetime, timedelta

import pytest

from service.controllers import statement_controller as controller
from service.errors import (
    LinkExpired,
    LinkInvalid,
    ObjectNotFound,
    StatementNotFound,
    StatementTooLarge,
    TtlExceedsMaximum,
)
from service.libs.security import issue_download_token, verify_download_token
from tests.conftest import CUSTOMER, SIGNING_KEY, FakeStore

PATH_PREFIX = "/api/v1/statements"
DOWNLOAD_PREFIX = f"{PATH_PREFIX}/downloads/"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # the default MAX_UPLOAD_BYTES


def _upload(
    store: FakeStore,
    *,
    data=b"%PDF",
    name="report.pdf",
    content_type="application/pdf",
    customer=CUSTOMER,
    max_bytes=MAX_UPLOAD_BYTES,
):
    return controller.upload_statement(
        store,
        customer_id=customer,
        raw_filename=name,
        raw_content_type=content_type,
        data=io.BytesIO(data),
        max_bytes=max_bytes,
    )


def _link(store, settings, statement_id, *, customer=CUSTOMER, ttl=None):
    return controller.create_download_link(
        store,
        settings,
        statement_id=statement_id,
        customer_id=customer,
        expiry_in_seconds=ttl,
        path_prefix=PATH_PREFIX,
    )


def _token(url: str) -> str:
    return url.rsplit("/downloads/", 1)[1]


@pytest.fixture
def stored(store: FakeStore):
    return _upload(store)


# ---- upload_statement ------------------------------------------------------------------------


def test_upload_generates_a_32_char_hex_id(store):
    stored = _upload(store)

    assert re.fullmatch(r"[0-9a-f]{32}", stored.statement_id)


def test_upload_generates_distinct_ids(store):
    assert _upload(store).statement_id != _upload(store).statement_id


def test_upload_accepts_a_statement_exactly_at_the_limit(store):
    stored = _upload(store, data=b"x" * 10, max_bytes=10)

    assert store.objects[stored.statement_id].data == b"x" * 10


def test_upload_rejects_a_statement_over_the_limit_and_stores_nothing(store):
    with pytest.raises(StatementTooLarge) as excinfo:
        _upload(store, data=b"x" * 11, max_bytes=10)

    assert excinfo.value.max_bytes == 10
    assert store.objects == {}


def test_upload_default_limit_is_ten_mebibytes(store):
    with pytest.raises(StatementTooLarge):
        _upload(store, data=b"x" * (MAX_UPLOAD_BYTES + 1))


def test_upload_writes_bytes_with_owner_and_metadata(store):
    stored = _upload(store, data=b"abc")

    blob = store.objects[stored.statement_id]
    assert blob.data == b"abc"
    assert blob.owner == CUSTOMER
    assert blob.filename == "report.pdf"
    assert blob.content_type == "application/pdf"


def test_upload_sanitises_client_filename(store):
    stored = _upload(store, name="../../evil name?.pdf")

    assert stored.filename == "evil_name_.pdf"


def test_upload_defaults_content_type_when_missing(store):
    stored = _upload(store, content_type=None)

    assert stored.content_type == "application/octet-stream"


def test_upload_returns_customer_id(store):
    assert _upload(store, customer="cust-X").customer_id == "cust-X"


# ---- create_download_link --------------------------------------------------------------------


def test_link_url_is_public_base_prefix_and_token(store, settings, stored):
    link = _link(store, settings, stored.statement_id, ttl=300)

    prefix = f"{settings.public_base_url}{DOWNLOAD_PREFIX}"
    assert link.url.startswith(prefix)
    claims = verify_download_token(link.url.removeprefix(prefix), SIGNING_KEY)
    assert claims["sub"] == stored.statement_id
    assert claims["own"] == CUSTOMER
    assert claims["fn"] == "report.pdf"


def test_expiry_follows_requested_ttl(store, settings, stored):
    before = datetime.now(UTC)

    link = _link(store, settings, stored.statement_id, ttl=600)

    assert timedelta(seconds=599) < link.expires_at - before <= timedelta(seconds=601)


def test_default_ttl_applies_when_none_requested(store, settings, stored):
    before = datetime.now(UTC)

    link = _link(store, settings, stored.statement_id, ttl=None)

    expected = timedelta(seconds=settings.link_default_ttl_seconds)
    assert expected - timedelta(seconds=2) < link.expires_at - before <= expected + timedelta(seconds=2)


def test_expiry_is_expressed_in_display_timezone(store, settings, stored):
    link = _link(store, settings, stored.statement_id, ttl=300)

    # Africa/Johannesburg is UTC+2 year-round (no daylight saving).
    assert link.expires_at.utcoffset() == timedelta(hours=2)


def test_ttl_above_maximum_raises(store, settings, stored):
    with pytest.raises(TtlExceedsMaximum) as excinfo:
        _link(store, settings, stored.statement_id, ttl=settings.link_max_ttl_seconds + 1)

    assert excinfo.value.max_seconds == settings.link_max_ttl_seconds


def test_ttl_is_checked_before_the_statement_is_looked_up(store, settings):
    # An unknown statement with an over-long TTL reports the TTL problem first.
    with pytest.raises(TtlExceedsMaximum):
        _link(store, settings, "0" * 32, ttl=settings.link_max_ttl_seconds + 1)


def test_unknown_statement_raises_not_found(store, settings):
    with pytest.raises(StatementNotFound):
        _link(store, settings, "0" * 32, ttl=300)


def test_other_customers_statement_raises_not_found(store, settings, stored):
    with pytest.raises(StatementNotFound):
        _link(store, settings, stored.statement_id, customer="cust-B", ttl=300)


# ---- get_download ----------------------------------------------------------------------------


def test_get_download_returns_filename_and_contents(store, settings, stored):
    token = _token(_link(store, settings, stored.statement_id, ttl=300).url)

    download = controller.get_download(store, settings, token=token)

    assert download.filename == "report.pdf"
    assert b"".join(download.stream.chunks) == b"%PDF"


def test_get_download_rejects_expired_token(store, settings, stored):
    token, _ = issue_download_token(
        object_key=stored.statement_id,
        filename="report.pdf",
        owner=CUSTOMER,
        signing_key=SIGNING_KEY,
        ttl_seconds=-5,
    )

    with pytest.raises(LinkExpired):
        controller.get_download(store, settings, token=token)


def test_get_download_rejects_token_signed_with_another_key(store, settings, stored):
    token, _ = issue_download_token(
        object_key=stored.statement_id,
        filename="report.pdf",
        owner=CUSTOMER,
        signing_key="x" * 40,
        ttl_seconds=300,
    )

    with pytest.raises(LinkInvalid):
        controller.get_download(store, settings, token=token)


def test_get_download_raises_when_object_was_deleted(store, settings, stored):
    token = _token(_link(store, settings, stored.statement_id, ttl=300).url)
    del store.objects[stored.statement_id]

    with pytest.raises(ObjectNotFound):
        controller.get_download(store, settings, token=token)
