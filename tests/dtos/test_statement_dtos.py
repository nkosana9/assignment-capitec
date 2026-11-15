"""DTO tests: the statement DTOs hold their fields and are immutable."""

import dataclasses
from datetime import UTC, datetime

import pytest

from service.dtos.statement_dtos import Download, IssuedLink, StoredStatement
from service.dtos.storage_dtos import ObjectInfo, ObjectStream


def test_stored_statement_holds_its_fields():
    stored = StoredStatement(statement_id="a" * 32, filename="r.pdf", content_type="application/pdf", customer_id="c1")

    assert stored.statement_id == "a" * 32
    assert stored.filename == "r.pdf"
    assert stored.content_type == "application/pdf"
    assert stored.customer_id == "c1"


def test_stored_statement_is_immutable():
    stored = StoredStatement(statement_id="a", filename="r.pdf", content_type="x", customer_id="c1")

    with pytest.raises(dataclasses.FrozenInstanceError):
        stored.filename = "other.pdf"


def test_issued_link_holds_url_and_expiry_and_is_immutable():
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    link = IssuedLink(url="https://files.example.test/x", expires_at=expires)

    assert link.url == "https://files.example.test/x"
    assert link.expires_at == expires
    with pytest.raises(dataclasses.FrozenInstanceError):
        link.url = "https://elsewhere.example.test"


def test_download_carries_filename_and_stream():
    info = ObjectInfo(content_type="text/plain", filename="a.txt", owner="c1", size=2)
    stream = ObjectStream(chunks=iter([b"hi"]), info=info)

    download = Download(filename="a.txt", stream=stream)

    assert download.filename == "a.txt"
    assert download.stream is stream
    with pytest.raises(dataclasses.FrozenInstanceError):
        download.filename = "b.txt"
