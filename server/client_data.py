# pyright: reportMissingImports=false

import asyncio
from typing import Optional

import shared.protocol as proto

class ClientData:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

        self.addr = writer.get_extra_info('peername')
        self.username: Optional[str] = None

    def set_name(self, name: str) -> None:
        if self.username is not None:
            if self.username == name:
                raise ValueError('User is already logged in as this username')

            raise ValueError('Username is already set')

        self.username = name

    async def respond(self, message: proto.Message) -> None:
        serialized = message.serialize()
        self.writer.write(serialized.encode())
        await self.writer.drain()
