from aionut import AIONUTClient, NUTError, NUTProtocolError


def test_imports():
    assert AIONUTClient()
    assert NUTError()
    assert NUTProtocolError()
