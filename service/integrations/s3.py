"""S3 implementation of the object store (currently RustFS but may be any S3-compatible server)."""

from collections.abc import Iterator, Mapping
from typing import BinaryIO

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from service.configuration.configuration import Settings
from service.dtos.storage_dtos import ObjectInfo, ObjectStream
from service.errors import ObjectNotFound

_CHUNK_SIZE = 64 * 1024
_FILENAME_META = "filename"
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
_OWNER_META = "owner"
# Multipart part size for uploads. S3 requires at least 5 MiB for every part except the last.
_UPLOAD_PART_SIZE = 8 * 1024 * 1024


def _info(size: int, content_type: str | None, metadata: Mapping[str, str] | None) -> ObjectInfo:
    """Create an ObjectInfo instance from S3 object metadata.

    Args:
        size: The size of the object in bytes.
        content_type: The content type of the object.
        metadata: The user-defined metadata of the object.

    Returns:
        An ObjectInfo instance populated with the provided metadata.
    """
    return ObjectInfo(
        size=size,
        content_type=content_type or "application/octet-stream",
        filename=(metadata or {}).get(_FILENAME_META, "download"),
        owner=(metadata or {}).get(_OWNER_META, ""),
    )


def _is_not_found(exception: ClientError) -> bool:
    """Check if an S3 ClientError corresponds to a not found error.

    Args:
        exception: The ClientError exception raised by boto3.

    Returns:
        True if the error indicates that the object or bucket was not found, False otherwise.
    """
    status = exception.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return status == 404 or exception.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES


def _s3_client(settings: Settings, config: Config):
    """Create an S3 client using the provided settings and configuration.

    Args:
        settings: The application settings containing S3 credentials and endpoint information.
        config: The botocore Config object for the S3 client.

    Returns:
        A boto3 S3 client instance.
    """
    scheme = "https" if settings.s3_secure else "http"
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{settings.s3_endpoint}",
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=config,
    )


class S3Store:
    """Provides an interface for interacting with an S3 bucket"""

    def __init__(self, client, bucket: str, probe_client=None) -> None:
        """Initialize the S3Store with the given client, bucket, and optional probe client.

        Args:
            client: The boto3 S3 client to use for operations.
            bucket: The name of the S3 bucket.
            probe_client: An optional S3 client for readiness probes.
        """
        self._client = client
        self._bucket = bucket
        # Readiness probes use a client with short timeouts, so a hung server cannot stall the probe.
        self._probe_client = probe_client or client

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3Store":
        """Build a store from application settings, with a fast-failing probe client.

        Args:
            settings: The application settings holding the S3 endpoint and credentials.

        Returns:
            An `S3Store` ready to use.
        """
        # Path-style addressing: RustFS and in-cluster service names do not support virtual hosts.
        addressing = {"addressing_style": "path"}
        client = _s3_client(
            settings,
            Config(signature_version="s3v4", s3=addressing),
        )
        probe_client = _s3_client(
            settings,
            Config(
                signature_version="s3v4",
                s3=addressing,
                connect_timeout=2,
                read_timeout=3,
                retries={"max_attempts": 1},
            ),
        )
        return cls(client, settings.s3_bucket, probe_client=probe_client)

    def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist.

        Raises:
            ClientError: If the bucket check fails for a reason other than not-found.
        """
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if not _is_not_found(exc):
                raise
            self._client.create_bucket(Bucket=self._bucket)

    def ping(self) -> None:
        """Check that the bucket is reachable, using the short-timeout probe client.

        Raises:
            ClientError: If the bucket cannot be accessed.
        """
        self._probe_client.head_bucket(Bucket=self._bucket)

    def put(self, key: str, data: BinaryIO, content_type: str, filename: str, owner: str) -> None:
        """Upload an object, using multipart transfer for large payloads.

        Args:
            key: The object key to write.
            data: The contents to upload.
            content_type: The MIME type to record on the object.
            filename: The original filename, stored as object metadata.
            owner: The customer the object belongs to, stored as object metadata.
        """
        self._client.upload_fileobj(
            data,
            self._bucket,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {_FILENAME_META: filename, _OWNER_META: owner},
            },
            Config=TransferConfig(
                multipart_threshold=_UPLOAD_PART_SIZE,
                multipart_chunksize=_UPLOAD_PART_SIZE,
            ),
        )

    def stat(self, key: str) -> ObjectInfo:
        """Fetch an object's metadata without downloading its contents.

        Args:
            key: The object key to look up.

        Returns:
            The object's size, content type, filename and owner.

        Raises:
            ObjectNotFound: If no object exists under `key`.
        """
        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFound(key) from exc
            raise
        return _info(resp["ContentLength"], resp.get("ContentType"), resp.get("Metadata"))

    def open(self, key: str) -> ObjectStream:
        """Open an object for streaming, returning its metadata and a chunk iterator.

        Args:
            key: The object key to open.

        Returns:
            The object's metadata together with an iterator over its contents.

        Raises:
            ObjectNotFound: If no object exists under `key`.
        """
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFound(key) from exc
            raise

        body = resp["Body"]

        def chunks() -> Iterator[bytes]:
            """Yield the object's contents in fixed-size chunks, closing the body when done."""
            try:
                yield from body.iter_chunks(_CHUNK_SIZE)
            finally:
                body.close()

        info = _info(resp["ContentLength"], resp.get("ContentType"), resp.get("Metadata"))
        return ObjectStream(info=info, chunks=chunks())
