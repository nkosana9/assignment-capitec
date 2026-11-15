"""Exceptions raised by the application"""


class ObjectNotFound(Exception):
    """The requested object does not exist in the bucket."""


class LinkError(Exception):
    """Base class for download-related failures."""


class LinkExpired(LinkError):
    pass


class LinkInvalid(LinkError):
    pass
