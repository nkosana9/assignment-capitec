"""DTO tests: the storage DTOs describe stored objects."""

import dataclasses

import pytest

from service.dtos.storage_dtos import ObjectInfo, ObjectStream


def test_object_info_holds_its_fields():
    info = ObjectInfo(content_type="application/pdf", filename="r.pdf", owner="c1", size=42)

    assert info.content_type == "application/pdf"
    assert info.filename == "r.pdf"
    assert info.owner == "c1"
    assert info.size == 42


def test_object_info_compares_by_value():
    a = ObjectInfo(content_type="x", filename="f", owner="o", size=1)
    b = ObjectInfo(content_type="x", filename="f", owner="o", size=1)

    assert a == b


def test_object_info_is_immutable():
    info = ObjectInfo(content_type="x", filename="f", owner="o", size=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        info.size = 2


def test_object_stream_pairs_metadata_with_chunks():
    info = ObjectInfo(content_type="x", filename="f", owner="o", size=3)

    stream = ObjectStream(chunks=iter([b"ab", b"c"]), info=info)

    assert stream.info is info
    assert b"".join(stream.chunks) == b"abc"
