from __future__ import annotations


class NUTError(Exception):
    """Base class for NUT errors."""


class NUTProtocolError(NUTError):
    """Raised when an unexpected response is received from the NUT server."""


class NUTLoginError(NUTError):
    """Raised when the login fails."""


class NUTCommandError(NUTError):
    """Raised when a command fails."""


class NUTOSError(NUTError):
    """Raised when an OS error occurs."""


class NUTTimeoutError(NUTError):
    """Raised when a timeout occurs."""


class NUTValueError(NUTError):
    """Raised when a value error occurs."""


class NUTShutdownError(NUTError):
    """Raised when the client is already shutdown."""


class NUTConnectionClosedError(NUTError):
    """Raised when the connection is closed."""


RETRY_ERRORS = (ValueError, OSError, TimeoutError)


def map_exception(exc: Exception) -> type[NUTError]:
    """Map an exception to a NUTError."""
    if isinstance(exc, TimeoutError):
        return NUTTimeoutError
    if isinstance(exc, ValueError):
        return NUTValueError
    if isinstance(exc, OSError):
        return NUTOSError
    return NUTError
