import asyncio
import socket
from asyncio.streams import StreamReader, StreamWriter
from typing import Callable

import pytest

from aionut import AIONUTClient, NUTError, NUTLoginError, NUTProtocolError


def test_imports():
    assert AIONUTClient()
    assert NUTError()
    assert NUTProtocolError()


@pytest.mark.asyncio
async def test_auth_late_auth_failure():
    port, close_server = await make_fake_nut_server(late_auth_failed=True)
    client = AIONUTClient(host="localhost", port=port, username="test", password="")
    with pytest.raises(NUTLoginError, match="LIST"):
        await client.list_ups()
    close_server()


@pytest.mark.asyncio
async def test_auth_bad_username():
    port, close_server = await make_fake_nut_server(bad_username=True)
    client = AIONUTClient(host="localhost", port=port, username="test", password="")
    with pytest.raises(NUTLoginError, match="USERNAME"):
        await client.list_ups()
    close_server()


@pytest.mark.asyncio
async def test_auth_bad_password():
    port, close_server = await make_fake_nut_server(bad_password=True)
    client = AIONUTClient(host="localhost", port=port, username="test", password="")
    with pytest.raises(NUTLoginError, match="PASSWORD"):
        await client.list_ups()
    close_server()


@pytest.mark.asyncio
async def test_list_ups():
    port, close_server = await make_fake_nut_server()
    client = AIONUTClient(host="localhost", port=port, username="test", password="")
    upses = await client.list_ups()
    assert upses == {"test": "bob"}
    close_server()


async def make_fake_nut_server(
    bad_username: bool = False,
    bad_password: bool = False,
    late_auth_failed: bool = False,
) -> tuple[int, Callable[[], None]]:

    async def handle_client(reader: StreamReader, writer: StreamWriter) -> None:
        while True:
            command = await reader.readline()
            if command.startswith(b"USERNAME"):
                if bad_username:
                    writer.write(b"ERR ACCESS-DENIED\n")
                    break
                writer.write(b"OK\n")
            elif command.startswith(b"PASSWORD"):
                if bad_password:
                    writer.write(b"ERR ACCESS-DENIED\n")
                    break
                writer.write(b"OK\n")
            elif late_auth_failed:
                writer.write(b"ERR ACCESS-DENIED\n")
                break
            elif command.startswith(b"LIST UPS"):
                writer.write(b"BEGIN LIST UPS\n")
                writer.write(b'UPS test "bob"\n')
                writer.write(b"END LIST UPS\n")
            else:
                writer.write(b"OK\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", 0))
    sock.listen(1000)
    port = sock.getsockname()[1]
    server = await asyncio.start_server(handle_client, sock=sock)
    task = asyncio.create_task(server.serve_forever())

    def close_server():
        server.close()
        sock.close()
        task.cancel()

    return port, close_server
