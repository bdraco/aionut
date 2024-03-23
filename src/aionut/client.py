from __future__ import annotations

import asyncio
from asyncio.streams import StreamReader, StreamWriter
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])


class NUTError(ValueError):
    """Base class for NUT errors."""


class NUTProtocolError(NUTError):
    """Raised when an unexpected response is received from the NUT server."""


class NutLoginError(NUTError):
    """Raised when the login fails."""


class NutCommandError(NUTError):
    """Raised when a command fails."""


def operation_lock(func: WrapFuncType) -> WrapFuncType:
    """Define a wrapper to only allow a single operation at a time."""

    async def _async_operation_lock_wrap(
        self: AIONutClient, *args: Any, **kwargs: Any
    ) -> None:
        """Lock the operation lock and run the function."""
        # pylint: disable=protected-access
        async with self._operation_lock:
            try:
                return await func(self, *args, **kwargs)
            except (NUTError, OSError) as err:
                await self.disconnect()
                raise err

    return cast(WrapFuncType, _async_operation_lock_wrap)


def ensure_connected(func: WrapFuncType) -> WrapFuncType:
    """Define a wrapper to only allow a single operation at a time."""

    async def _async_ensure_connected_wrap(
        self: AIONutClient, *args: Any, **kwargs: Any
    ) -> None:
        """Ensure we are connected to the NUT server."""
        # pylint: disable=protected-access
        if not self._connected:
            await self._connect()

        result = await func(self, *args, **kwargs)

        if not self._persistent:
            await self.disconnect()

        return result

    return cast(WrapFuncType, _async_ensure_connected_wrap)


class AIONutClient:
    """A client for the NUT (Network UPS Tools) protocol."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3493,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 5,
        persistent: bool = True,
    ) -> None:
        """Initialize the NUT client."""
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._persistent = persistent
        self._reader: StreamReader | None = None
        self._writer: StreamWriter | None = None
        self._connected: bool = False
        self._operation_lock = asyncio.Lock()

    async def _connect(self) -> None:
        """Connect to the NUT server."""
        if not self._connected:
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )
            if self.username is not None:
                self._write(f"USERNAME {self.username}\n")
                response = await self._reader.readline()
                if not response.startswith(b"OK"):
                    raise NutLoginError(f"Unexpected response: {response!r}")

            if self.password is not None:
                self._write(f"PASSWORD {self.password}\n")
                response = await self._reader.readline()
                if not response.startswith(b"OK"):
                    raise NutLoginError(f"Unexpected response: {response!r}")

            self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the NUT server."""
        if self._connected and self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._connected = False
            self._writer = None
            self._reader = None

    def _write(self, data: str) -> None:
        """Write data to the NUT server."""
        if TYPE_CHECKING:
            assert self._writer is not None
        self._writer.write(data.encode("ascii"))

    @operation_lock
    @ensure_connected
    async def description(self, ups: str) -> str:
        """Get the description of a UPS."""
        # Send: GET UPSDESC <upsname>
        # Return: UPSDESC <upsname> <description>
        if TYPE_CHECKING:
            assert self._reader is not None
        self._write(f"GET UPSDESC {ups}\n")
        response = await self._reader.readline()
        if not response.startswith(b"UPSDESC"):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        _, _, description = response.decode("ascii").split(" ", 2)
        return description

    @operation_lock
    @ensure_connected
    async def list_ups(self) -> dict[str, str]:
        """
        List the available UPSes.

        Returns a dictionary of UPS names and descriptions.
        """
        # Send: LIST UPS
        # Return: BEGIN LIST UPS
        # UPS <upsname> "<description>"
        # ...
        # END LIST UPS
        if TYPE_CHECKING:
            assert self._reader is not None
        self._write("LIST UPS\n")
        response = await self._reader.readuntil(b"END LIST UPS\n")
        if not response.startswith(b"UPS"):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        return {
            parts[1]: parts[2].strip('"')
            for line in response.decode("ascii").splitlines()
            if line.startswith("UPS ") and (parts := line.split(" ", 2))
        }

    @operation_lock
    @ensure_connected
    async def list_vars(self, ups: str) -> dict[str, str]:
        """
        List the available variables for a UPS.

        Returns a dictionary of var name and var description.
        """
        # Send: LIST VAR <upsname>
        # Return: BEGIN LIST VAR <upsname>
        # VAR <upsname> <varname> "<value>"
        # ...
        # END LIST VAR <upsname>
        if TYPE_CHECKING:
            assert self._reader is not None
        self._write(f"LIST VAR {ups}\n")
        response = await self._reader.readuntil(f"END LIST VAR {ups}\n".encode("ascii"))
        if not response.startswith(f"BEING LIST VAR {ups}".encode("ascii")):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        return {
            parts[2]: parts[3].strip('"')
            for line in response.decode("ascii").splitlines()
            if line.startswith("VAR ") and (parts := line.split(" ", 3))
        }

    @operation_lock
    @ensure_connected
    async def list_commands(self, ups: str) -> set[str]:
        """
        List the available commands for a UPS.

        Returns a list of command names.
        """
        # Send: LIST CMD <upsname>
        # Return: BEGIN LIST CMD <upsname>
        # CMD <upsname> <cmdname>
        # ...
        # END LIST CMD <upsname>
        if TYPE_CHECKING:
            assert self._reader is not None
        self._write(f"LIST CMD {ups}\n")
        response = await self._reader.readuntil(f"END LIST CMD {ups}\n".encode("ascii"))
        if not response.startswith(f"BEING LIST CMD {ups}".encode("ascii")):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        return {
            parts[2].strip('"')
            for line in response.decode("ascii").splitlines()
            if line.startswith("CMD ") and (parts := line.split(" ", 2))
        }

    @operation_lock
    @ensure_connected
    async def run_command(
        self, ups: str, command: str, param: str | None = None
    ) -> str:
        """
        Run a command for a UPS.

        Returns the response from the command.
        """
        # Send: INSTCMD <upsname> <cmdname> [<cmdparam>]
        # Return: OK <response>
        #         ERR <error>
        if TYPE_CHECKING:
            assert self._reader is not None
        if param is not None:
            self._write(f"INSTCMD {ups} {command} {param}\n")
        else:
            self._write(f"INSTCMD {ups} {command}\n")
        response = await self._reader.readline()
        if not response.startswith(b"OK"):
            raise NutCommandError(
                f"Error running command: {response.decode('ascii').strip()}"
            )
        return response.decode("ascii").strip()
