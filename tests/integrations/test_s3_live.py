"""End-to-end checks against a live S3-compatible server (RustFS).

Skipped unless S3_INTEGRATION=1. Uses S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY / S3_SECURE
(defaults: localhost:9000, rustfsadmin/rustfsadmin) and a throwaway bucket.
"""

import io
import os
import time
import uuid

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.testclient import TestClient

from service.configuration.configuration import Settings
from service.errors import ObjectNotFound
from service.integrations.s3 import S3Store
from service.server import create_app
from tests.conftest import API_KEY, CUSTOMER, SIGNING_KEY

pytestmark = pytest.mark.skipif(
    os.environ.get("S3_INTEGRATION") != "1",
    reason="set S3_INTEGRATION=1 to run against a live S3 server",
)


def _raw_client(settings: Settings):
    scheme = "https" if settings.s3_secure else "http"
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{settings.s3_endpoint}",
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@pytest.fixture
def s3_settings():
    bucket = f"test-{uuid.uuid4().hex[:12]}"
    settings = Settings(
        api_key=API_KEY,
        link_signing_key=SIGNING_KEY,
        public_base_url="https://files.example.test",
        s3_endpoint=os.environ.get("S3_ENDPOINT", "localhost:9000"),
        s3_access_key=os.environ.get("S3_ACCESS_KEY", "rustfsadmin"),
        s3_secret_key=os.environ.get("S3_SECRET_KEY", "rustfsadmin"),
        s3_secure=os.environ.get("S3_SECURE", "false") == "true",
        s3_bucket=bucket,
        _env_file=None,
    )
    yield settings
    client = _raw_client(settings)
    try:
        listing = client.list_objects_v2(Bucket=bucket).get("Contents", [])
        for obj in listing:
            client.delete_object(Bucket=bucket, Key=obj["Key"])
        client.delete_bucket(Bucket=bucket)
    except client.exceptions.NoSuchBucket:
        pass


def test_full_flow_against_s3(s3_settings):
    store = S3Store.from_settings(s3_settings)
    auth = {"X-API-Key": API_KEY}
    payload = os.urandom(3 * 1024 * 1024)  # forces multi-chunk streaming

    with TestClient(create_app(s3_settings, store)) as client:  # runs ensure_bucket
        up = client.post(
            "/api/v1/statements",
            headers=auth,
            data={"customer_id": CUSTOMER},
            files={"statement": ("big report.bin", io.BytesIO(payload), "application/octet-stream")},
        )
        assert up.status_code == 201, up.text
        statement_id = up.json()["statement_id"]

        link = client.post(
            f"/api/v1/statements/{statement_id}/links",
            headers=auth,
            json={"customer_id": CUSTOMER, "expires_in_seconds": 120},
        )
        assert link.status_code == 200, link.text
        path = link.json()["url"].replace("https://files.example.test", "")

        dl = client.get(path)
        assert dl.status_code == 200
        assert dl.content == payload
        assert dl.headers["content-disposition"] == 'attachment; filename="big_report.bin"'
        assert dl.headers["content-length"] == str(len(payload))

        # The owner is stored as S3 metadata and comes back on stat.
        assert store.stat(statement_id).owner == CUSTOMER

        other = client.post(
            f"/api/v1/statements/{statement_id}/links",
            headers=auth,
            json={"customer_id": "someone-else"},
        )
        assert other.status_code == 404


def test_missing_object_maps_to_not_found(s3_settings):
    store = S3Store.from_settings(s3_settings)
    store.ensure_bucket()

    with pytest.raises(ObjectNotFound):
        store.stat("0" * 32)
    with pytest.raises(ObjectNotFound):
        store.open("0" * 32)


def test_ping_succeeds_against_live_storage(s3_settings):
    store = S3Store.from_settings(s3_settings)
    store.ensure_bucket()

    store.ping()  # must not raise


def test_ping_fails_fast_when_storage_is_unreachable(s3_settings):
    # A copy, so the fixture's teardown still talks to the live server.
    unreachable = s3_settings.model_copy(update={"s3_endpoint": "127.0.0.1:1"})  # nothing listens here
    store = S3Store.from_settings(unreachable)

    start = time.monotonic()
    # Connection failures surface as botocore errors (BotoCoreError); server errors as ClientError.
    with pytest.raises((BotoCoreError, ClientError)):
        store.ping()
    # The probe client has a 2s connect timeout and a single attempt, so it must fail well under 10s.
    assert time.monotonic() - start < 10
