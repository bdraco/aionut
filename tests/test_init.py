import asyncio
import contextlib
import logging
import socket
from asyncio.streams import StreamReader, StreamWriter

import pytest

from aionut import (
    AIONUTClient,
    NUTCommandError,
    NUTConnectionClosedError,
    NUTError,
    NUTLoginError,
    NUTProtocolError,
    NUTShutdownError,
    NUTTimeoutError,
)

_LOGGER = logging.getLogger("aionut")
_LOGGER.setLevel(logging.DEBUG)
logging.basicConfig(level=logging.DEBUG)


def test_imports():
    assert AIONUTClient()
    assert NUTError()
    assert NUTProtocolError()


_CLIENTS: set[AIONUTClient] = set()
_SERVERS: set[tuple[asyncio.Server, asyncio.Task[None], socket.socket]] = set()


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await asyncio.sleep(0)
    _LOGGER.debug("cleanup")
    for client in _CLIENTS:
        writer = client._writer
        assert writer
        writer.write_eof()
        await writer.drain()
        client.shutdown()
        await writer.wait_closed()
    for server, task, sock in _SERVERS:
        server.close()
        await server.wait_closed()
        sock.close()
        for sock in server.sockets:
            sock.close()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await asyncio.sleep(0)
    _CLIENTS.clear()
    _SERVERS.clear()


def make_nut_client(port: int) -> AIONUTClient:
    client = AIONUTClient(
        host="localhost", port=port, username="test", password="", timeout=0.1
    )
    _CLIENTS.add(client)
    return client


@pytest.mark.asyncio
async def test_auth_late_auth_failure():
    port = await make_fake_nut_server(late_auth_failed=True)
    client = make_nut_client(port)
    with pytest.raises(NUTLoginError, match="LIST"):
        await client.list_ups()


@pytest.mark.asyncio
async def test_auth_bad_username():
    port = await make_fake_nut_server(bad_username=True)
    client = make_nut_client(port)
    with pytest.raises(NUTLoginError, match="USERNAME"):
        await client.list_ups()


@pytest.mark.asyncio
async def test_auth_bad_password():
    port = await make_fake_nut_server(bad_password=True)
    client = make_nut_client(port)
    with pytest.raises(NUTLoginError, match="PASSWORD"):
        await client.list_ups()


@pytest.mark.asyncio
async def test_list_ups():
    port = await make_fake_nut_server()
    client = make_nut_client(port)
    upses = await client.list_ups()
    assert upses == {"test": "bob"}


@pytest.mark.asyncio
async def test_list_vars():
    port = await make_fake_nut_server()
    client = make_nut_client(port)
    vars = await client.list_vars("test")
    assert vars == {"x.y": "z"}


@pytest.mark.asyncio
async def test_list_command():
    port = await make_fake_nut_server()
    client = make_nut_client(port)
    commands = await client.list_commands("test")
    assert commands == {"valid"}


@pytest.mark.asyncio
async def test_list_ups_first_connection_drop():
    port = await make_fake_nut_server(drop_first_connection=True)
    client = make_nut_client(port)
    upses = await client.list_ups()
    assert upses == {"test": "bob"}


@pytest.mark.asyncio
async def test_list_ups_connection_drop():
    port = await make_fake_nut_server(drop_connection=True)
    client = make_nut_client(port)
    with pytest.raises(NUTConnectionClosedError):
        await client.list_ups()


@pytest.mark.asyncio
async def test_run_command():
    port = await make_fake_nut_server()
    client = make_nut_client(port)
    with pytest.raises(NUTCommandError, match="UNKNOWN-COMMAND"):
        await client.run_command("test", "invalid")

    assert await client.run_command("test", "valid") == "OK"
    assert await client.run_command("test", "param", "param") == "OK"


@pytest.mark.asyncio
async def test_description():
    port = await make_fake_nut_server()
    client = make_nut_client(port)
    assert await client.description("test") == "demo ups"


@pytest.mark.asyncio
async def test_timeout():
    port = await make_fake_nut_server()
    client = make_nut_client(port)
    with pytest.raises(NUTTimeoutError):
        await client.run_command("test", "no_response")


@pytest.mark.asyncio
async def test_use_after_shutdown():
    port = await make_fake_nut_server()
    client = make_nut_client(port)
    client.shutdown()
    with pytest.raises(NUTShutdownError):
        await client.description("test")


async def make_fake_nut_server(
    bad_username: bool = False,
    bad_password: bool = False,
    late_auth_failed: bool = False,
    drop_first_connection: bool = False,
    drop_connection: bool = False,
) -> int:

    dropped_connection = False

    async def handle_client(reader: StreamReader, writer: StreamWriter) -> None:
        nonlocal dropped_connection
        while True:
            if writer.is_closing():
                break
            command = await reader.readline()
            if command == b"":
                break
            if drop_connection or (drop_first_connection and not dropped_connection):
                dropped_connection = True
                break
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
            elif command.startswith(b"LIST VAR"):
                writer.write(b"BEGIN LIST VAR test\n")
                writer.write(b'VAR test x.y "z"\n')
                writer.write(b"END LIST VAR test\n")
            elif command.startswith(b"LIST CMD"):
                writer.write(b"BEGIN LIST CMD test\n")
                writer.write(b'CMD test "valid"\n')
                writer.write(b"END LIST CMD test\n")
            elif command.startswith(b"INSTCMD test no_response"):
                pass
            elif command.startswith(b"INSTCMD test invalid"):
                writer.write(b"ERR UNKNOWN-COMMAND\n")
            elif command.startswith(b"INSTCMD test valid"):
                writer.write(b"OK\n")
            elif command.startswith(b"INSTCMD test param param"):
                writer.write(b"OK\n")
            elif command.startswith(b"GET UPSDESC test"):
                writer.write(b'UPSDESC test "demo ups"\n')
            else:
                writer.write(b"ERR\n")

        writer.close()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("", 0))
    sock.listen(1000)
    port = sock.getsockname()[1]
    server = await asyncio.start_server(handle_client, sock=sock)
    task = asyncio.create_task(server.serve_forever())
    _SERVERS.add((server, task, sock))
    return port
