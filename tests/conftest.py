import io
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from service.configuration.configuration import Settings
from service.dtos.storage_dtos import ObjectInfo, ObjectStream
from service.errors import ObjectNotFound
from service.server import create_app

API_KEY = "test-api-key-0123456789"
SIGNING_KEY = "signing-key-0123456789abcdef0123456789"
CUSTOMER = "cust-1"


@dataclass
class StoredBlob:
    data: bytes
    content_type: str
    filename: str
    owner: str


class FakeStore:
    """In-memory stand-in for S3Store, satisfying the ObjectStore protocol."""

    def __init__(self) -> None:
        self.objects: dict[str, StoredBlob] = {}
        self.reachable = True  # set to False to simulate an unreachable storage server

    def ensure_bucket(self) -> None:
        pass

    def ping(self) -> None:
        if not self.reachable:
            raise ConnectionError("storage is down")

    def put(self, key: str, data, content_type: str, filename: str, owner: str) -> None:
        self.objects[key] = StoredBlob(data.read(), content_type, filename, owner)

    def stat(self, key: str) -> ObjectInfo:
        blob = self._get(key)
        return ObjectInfo(size=len(blob.data), content_type=blob.content_type, filename=blob.filename, owner=blob.owner)

    def open(self, key: str) -> ObjectStream:
        blob = self._get(key)
        info = ObjectInfo(size=len(blob.data), content_type=blob.content_type, filename=blob.filename, owner=blob.owner)
        return ObjectStream(info=info, chunks=iter([blob.data]))

    def _get(self, key: str) -> StoredBlob:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return self.objects[key]


@pytest.fixture
def settings() -> Settings:
    # _env_file=None keeps a developer's local .env from leaking into the tests.
    return Settings(
        api_key=API_KEY,
        link_signing_key=SIGNING_KEY,
        public_base_url="https://files.example.test",
        _env_file=None,
    )


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def client(settings: Settings, store: FakeStore) -> Iterator[TestClient]:
    with TestClient(create_app(settings, store)) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def upload(
    client: TestClient,
    auth: dict,
    name: str = "report.pdf",
    data: bytes = b"%PDF-demo",
    customer: str = CUSTOMER,
) -> str:
    resp = client.post(
        "/api/v1/statements",
        headers=auth,
        data={"customer_id": customer},
        files={"statement": (name, io.BytesIO(data), "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["statement_id"]
