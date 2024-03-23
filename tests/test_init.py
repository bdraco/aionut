from aionut import AIONutClient, NUTError, NUTProtocolError


def test_imports():
    assert AIONutClient()
    assert NUTError()
    assert NUTProtocolError()
