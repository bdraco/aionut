from __future__ import annotations

import asyncio
import logging
from asyncio.streams import StreamReader, StreamWriter
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

_LOGGER = logging.getLogger(__name__)

WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])


class NUTError(Exception):
    """Base class for NUT errors."""


class NUTProtocolError(NUTError):
    """Raised when an unexpected response is received from the NUT server."""


class NutLoginError(NUTError):
    """Raised when the login fails."""


class NutCommandError(NUTError):
    """Raised when a command fails."""


RETRY_ERRORS = (ValueError, OSError, TimeoutError)


def connected_operation(func: WrapFuncType) -> WrapFuncType:
    """Define a wrapper to only allow a single operation at a time."""

    async def _async_connected_operation_wrap(
        self: AIONutClient, *args: Any, **kwargs: Any
    ) -> None:
        """Lock the operation lock and run the function."""
        # pylint: disable=protected-access
        async with self._operation_lock:
            for attempt in range(2):
                try:
                    if not self._connected:
                        await self._connect()
                    return await func(self, *args, **kwargs)
                except NUTError:
                    await self.disconnect()
                    raise
                except RETRY_ERRORS as err:
                    await self.disconnect()
                    if attempt == 1:
                        raise err

            if not self._persistent:
                await self.disconnect()

    return cast(WrapFuncType, _async_connected_operation_wrap)


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
        self.timeout = timeout
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
            async with asyncio.timeout(self.timeout):
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )
            if self.username is not None:
                try:
                    response = await self._write_command_or_raise(
                        f"USERNAME {self.username}\n"
                    )
                except NutCommandError as err:
                    raise NutLoginError(f"Error setting username: {response}") from err

            if self.password is not None:
                try:
                    response = await self._write_command_or_raise(
                        f"PASSWORD {self.password}\n"
                    )
                except NutCommandError as err:
                    raise NutLoginError(f"Error setting password: {response}") from err

            self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the NUT server."""
        if self._connected and self._writer is not None:
            writer = self._writer
            writer.close()
            self._connected = False
            self._writer = None
            self._reader = None

    async def _write_command_or_raise(self, data: str) -> str:
        """Write a command, read a response from the NUT server or raise an error."""
        if TYPE_CHECKING:
            assert self._writer is not None
        if TYPE_CHECKING:
            assert self._reader is not None
        outgoing = data.encode("ascii")
        _LOGGER.debug("[%s:%s] Sending: %s", self.host, self.port, outgoing)
        self._writer.write(outgoing)
        async with asyncio.timeout(self.timeout):
            response = await self._reader.readline()
        _LOGGER.debug("[%s:%s] Received: %s", self.host, self.port, response)
        if response.startswith(b"ERR"):
            raise NutCommandError(
                f"Error running command: {response.decode('ascii').strip()}"
            )
        return response.decode("ascii")

    async def _read_util(self, data: str) -> str:
        """Read until the end of a response."""
        if TYPE_CHECKING:
            assert self._reader is not None
        async with asyncio.timeout(self.timeout):
            response = await self._reader.readuntil(data.encode("ascii"))
        _LOGGER.debug("[%s:%s] Received: %s", self.host, self.port, response)
        return response.decode("ascii")

    @connected_operation
    async def description(self, ups: str) -> str:
        """Get the description of a UPS."""
        # Send: GET UPSDESC <upsname>
        # Return: UPSDESC <upsname> <description>
        response = await self._write_command_or_raise(f"GET UPSDESC {ups}\n")
        if not response.startswith("UPSDESC"):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        _, _, description = response.split(" ", 2)
        return description

    @connected_operation
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
        response = await self._write_command_or_raise("LIST UPS\n")
        if not response.startswith("BEGIN LIST UPS"):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        response = await self._read_util("END LIST UPS\n")
        if not response.startswith("UPS"):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        return {
            parts[1]: parts[2].strip('"')
            for line in response.splitlines()
            if line.startswith("UPS ") and (parts := line.split(" ", 2))
        }

    @connected_operation
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
        response = await self._write_command_or_raise(f"LIST VAR {ups}\n")
        if not response.startswith(f"BEGIN LIST VAR {ups}"):
            raise NUTProtocolError(f"Unexpected response: {response!r}")
        response = await self._read_util(f"END LIST VAR {ups}\n")
        return {
            parts[2]: parts[3].strip('"')
            for line in response.splitlines()
            if line.startswith("VAR ") and (parts := line.split(" ", 3))
        }

    @connected_operation
    async def list_commands(self, ups: str) -> set[str]:
        """
        List the available commands for a UPS.

        Returns a set of command names.
        """
        # Send: LIST CMD <upsname>
        # Return: BEGIN LIST CMD <upsname>
        # CMD <upsname> <cmdname>
        # ...
        # END LIST CMD <upsname>
        if TYPE_CHECKING:
            assert self._reader is not None
        response = await self._write_command_or_raise(f"LIST CMD {ups}\n")
        if not response.startswith(f"BEGIN LIST CMD {ups}"):
            raise NUTProtocolError(f"Unexpected response: {response}")
        response = await self._read_util(f"END LIST CMD {ups}\n")
        return {
            parts[2].strip('"')
            for line in response.splitlines()
            if line.startswith("CMD ") and (parts := line.split(" ", 2))
        }

    @connected_operation
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
        command = f"INSTCMD {ups} {command}"
        if param:
            command = f"{command} {param}"
        response = await self._write_command_or_raise(f"{command}\n")
        return response.strip()
