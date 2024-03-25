import logging

from aionut.exceptions import (
    NUTError,
    NUTOSError,
    NUTTimeoutError,
    NUTValueError,
    map_exception,
)

_LOGGER = logging.getLogger("aionut")
_LOGGER.setLevel(logging.DEBUG)
logging.basicConfig(level=logging.DEBUG)


def test_map_exception():
    assert map_exception(TimeoutError()) == NUTTimeoutError
    assert map_exception(ValueError()) == NUTValueError
    assert map_exception(OSError()) == NUTOSError
    assert map_exception(RuntimeError()) == NUTError
