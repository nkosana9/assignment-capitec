"""Integration-layer tests for S3Store, run against botocore's Stubber (no server needed).

Each test scripts the exact S3 responses or errors it expects, so the store's translation of
S3 behaviour (not-found mapping, metadata defaults, client configuration) is checked in isolation.
"""

import io
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from service.configuration.configuration import Settings
from service.dtos.storage_dtos import ObjectInfo
from service.errors import ObjectNotFound
from service.integrations.s3 import S3Store
from tests.conftest import API_KEY, CUSTOMER, SIGNING_KEY

BUCKET = "downloads"
KEY = "a" * 32


@pytest.fixture
def raw_client():
    # The endpoint is never contacted: Stubber intercepts every call made through this client.
    return boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:9",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )


@pytest.fixture
def stubber(raw_client):
    with Stubber(raw_client) as stub:
        yield stub
        stub.assert_no_pending_responses()


@pytest.fixture
def store(raw_client) -> S3Store:
    return S3Store(raw_client, BUCKET)


# ---- ensure_bucket / ping --------------------------------------------------------------------


def test_ensure_bucket_leaves_an_existing_bucket_alone(store, stubber):
    stubber.add_response("head_bucket", {}, {"Bucket": BUCKET})

    store.ensure_bucket()


def test_ensure_bucket_creates_a_missing_bucket(store, stubber):
    stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
    stubber.add_response("create_bucket", {}, {"Bucket": BUCKET})

    store.ensure_bucket()


def test_ensure_bucket_reraises_other_errors(store, stubber):
    stubber.add_client_error("head_bucket", service_error_code="AccessDenied", http_status_code=403)

    with pytest.raises(ClientError):
        store.ensure_bucket()


def test_ping_succeeds_when_bucket_is_reachable(store, stubber):
    stubber.add_response("head_bucket", {}, {"Bucket": BUCKET})

    store.ping()


def test_ping_raises_when_bucket_is_unreachable(store, stubber):
    stubber.add_client_error("head_bucket", service_error_code="ServiceUnavailable", http_status_code=503)

    with pytest.raises(ClientError):
        store.ping()


# ---- stat ------------------------------------------------------------------------------------


def test_stat_maps_head_object_to_object_info(store, stubber):
    stubber.add_response(
        "head_object",
        {
            "ContentLength": 3,
            "ContentType": "application/pdf",
            "Metadata": {"filename": "report.pdf", "owner": CUSTOMER},
        },
        {"Bucket": BUCKET, "Key": KEY},
    )

    info = store.stat(KEY)

    assert info == ObjectInfo(size=3, content_type="application/pdf", filename="report.pdf", owner=CUSTOMER)


def test_stat_defaults_missing_metadata(store, stubber):
    stubber.add_response("head_object", {"ContentLength": 0}, {"Bucket": BUCKET, "Key": KEY})

    info = store.stat(KEY)

    assert info.content_type == "application/octet-stream"
    assert info.filename == "download"
    assert info.owner == ""


def test_stat_maps_not_found_to_object_not_found(store, stubber):
    stubber.add_client_error("head_object", service_error_code="404", http_status_code=404)

    with pytest.raises(ObjectNotFound):
        store.stat(KEY)


def test_stat_reraises_other_errors(store, stubber):
    stubber.add_client_error("head_object", service_error_code="InternalError", http_status_code=500)

    with pytest.raises(ClientError):
        store.stat(KEY)


# ---- open ------------------------------------------------------------------------------------


def test_open_streams_the_object_body(store, stubber):
    body = StreamingBody(io.BytesIO(b"hello"), 5)
    stubber.add_response(
        "get_object",
        {
            "ContentLength": 5,
            "ContentType": "text/plain",
            "Metadata": {"filename": "a.txt", "owner": CUSTOMER},
            "Body": body,
        },
        {"Bucket": BUCKET, "Key": KEY},
    )

    stream = store.open(KEY)

    assert stream.info == ObjectInfo(size=5, content_type="text/plain", filename="a.txt", owner=CUSTOMER)
    assert b"".join(stream.chunks) == b"hello"


def test_open_maps_not_found_to_object_not_found(store, stubber):
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)

    with pytest.raises(ObjectNotFound):
        store.open(KEY)


# ---- put -------------------------------------------------------------------------------------


def test_put_uploads_with_content_type_and_metadata():
    raw = MagicMock()
    store = S3Store(raw, BUCKET)

    store.put(KEY, io.BytesIO(b"x"), content_type="application/pdf", filename="report.pdf", owner=CUSTOMER)

    args, kwargs = raw.upload_fileobj.call_args
    assert args[1:3] == (BUCKET, KEY)
    assert kwargs["ExtraArgs"] == {
        "ContentType": "application/pdf",
        "Metadata": {"filename": "report.pdf", "owner": CUSTOMER},
    }
    assert kwargs["Config"].multipart_threshold == 8 * 1024 * 1024


# ---- from_settings ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    base = {
        "api_key": API_KEY,
        "link_signing_key": SIGNING_KEY,
        "s3_endpoint": "storage.internal:9000",
        "s3_bucket": BUCKET,
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


def test_from_settings_targets_the_configured_endpoint_over_http():
    store = S3Store.from_settings(_settings(s3_secure=False))

    assert store._client.meta.endpoint_url == "http://storage.internal:9000"


def test_from_settings_uses_https_when_secure():
    store = S3Store.from_settings(_settings(s3_secure=True))

    assert store._client.meta.endpoint_url == "https://storage.internal:9000"


def test_from_settings_uses_path_style_addressing():
    store = S3Store.from_settings(_settings())

    assert store._client.meta.config.s3["addressing_style"] == "path"


def test_from_settings_gives_the_probe_client_short_timeouts():
    store = S3Store.from_settings(_settings())

    assert store._probe_client.meta.config.connect_timeout == 2
    assert store._probe_client.meta.config.read_timeout == 3
    assert store._probe_client is not store._client
