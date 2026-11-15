"""Exceptions raised by the application"""


class ObjectNotFound(Exception):
    """The requested object does not exist in the bucket."""


class StatementNotFound(Exception):
    """No statement with this ID exists for the requesting customer."""


class TtlExceedsMaximum(Exception):
    """The requested link lifetime is longer than the configured maximum."""

    def __init__(self, max_seconds: int) -> None:
        """Record the maximum allowed lifetime in the error.

        Args:
            max_seconds: The configured maximum link lifetime, in seconds.
        """
        super().__init__(f"TTL must be at most {max_seconds} seconds")
        self.max_seconds = max_seconds


class StatementTooLarge(Exception):
    """The uploaded statement is larger than the configured maximum."""

    def __init__(self, max_bytes: int) -> None:
        """Record the maximum allowed upload size in the error.

        Args:
            max_bytes: The configured maximum upload size, in bytes.
        """
        super().__init__(f"Statement must be at most {max_bytes} bytes")
        self.max_bytes = max_bytes


class LinkError(Exception):
    """Base class for download-related failures."""


class LinkExpired(LinkError):
    """The download token's expiry time has passed."""


class LinkInvalid(LinkError):
    """The download token is malformed, has a bad signature, or fails validation."""
