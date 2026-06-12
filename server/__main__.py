# Pyright keeps acting up about server.database and shared.protocol, even though they exist
# So, I'm muting the import errors for now
# pyright: reportMissingImports=false

import os
import logging
import asyncio
import argparse
from typing import Optional
import mysql.connector
import dotenv

from server.database import execute_migrations
import shared.protocol as proto

LOGGER = logging.getLogger(__name__)

#: The default port that the server binds onto when no port is specified
DEFAULT_PORT = 12345

class ClientData:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

        self.addr = writer.get_extra_info('peername')
        self.username: Optional[str] = None

    def set_name(self, name: str) -> None:
        if self.username is not None:
            raise ValueError('Username is already set')

        self.username = name

    async def respond(self, message: proto.Message) -> None:
        serialized = message.serialize()
        self.writer.write(serialized.encode())
        await self.writer.drain()

class ServerState:
    def __init__(
        self,
        format: str = '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt: str = '%Y-%m-%d %H:%M:%S'
    ) -> None:
        parser = argparse.ArgumentParser(
            prog='Chat - Server',
            description='The server-side code of a chat application made as the final project for Computer Science class',
        )

        parser.add_argument('--host', '-H', default='localhost', help='The host to bind the server to')
        parser.add_argument('--port', '-P', default=12345, type=int, help='The port to bind the server to')

        parser.add_argument('--no-debug', dest='debug', action='store_false', help='Disable debug mode (enabled by default)')
        parser.add_argument(
            '--logfile',
            '-L',
            help='Path to a file to log to (if not specified, logs will be written to logs/server.log)',
            default='logs/server.log'
        )

        self._args = parser.parse_args()

        handlers: list[logging.Handler] = [
            logging.FileHandler(self.logfile)
        ]

        if self.debug:
            handlers.append(logging.StreamHandler())

        logging.basicConfig(
            level=self.loglevel,
            format=format,
            datefmt=datefmt,
            handlers=handlers
        )

        self.clients: set[ClientData] = set()
        self.server = None

        self.db_pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name='chat_server_pool',
            pool_size=5,
            host=os.getenv('MYSQL_HOST', 'localhost'),
            port=int(os.getenv('MYSQL_PORT', '3306')),
            user=os.getenv('MYSQL_USER', 'root'),
            password=os.getenv('MYSQL_PASSWORD', ''),
        )

    async def bind(self) -> None:
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        LOGGER.info(f'Server bound to {self.host}:{self.port}')

    async def _process_message(
        self,
        message: proto.Message,
        sender: ClientData,
    ) -> None:
        if message.type != proto.MessageType.REQUEST:
            LOGGER.warning(f'Ignoring non-request message from {sender.username or sender.addr}')
            return

        match message.kind:
            case proto.MessageKind.CONNECT:
                try:
                    sender.set_name(message.payload[proto.PayloadField.REQ_CONNECT_USERNAME])
                    LOGGER.info(f'Client {sender.addr} set their username to {sender.username}')

                    await sender.respond(proto.Message(
                        type_=proto.MessageType.RESPONSE,
                        kind=proto.MessageKind.CONNECTED,
                        payload={
                            proto.PayloadField.RESP_SUCCESS: True,
                            proto.PayloadField.RESP_CONNECTED_USER: sender.username
                        }
                    ))
                except ValueError as e:
                    LOGGER.warning(f'Client {sender.addr} attempted to set their username to {message.payload[proto.PayloadField.REQ_CONNECT_USERNAME]}, but it was already set to {sender.username}')

                    await sender.respond(proto.Message(
                        type_=proto.MessageType.ERROR,
                        kind=proto.MessageKind.CONNECTED,
                        payload={
                            proto.PayloadField.RESP_SUCCESS: False,
                            proto.PayloadField.RESP_ERROR: str(e)
                        }
                    ))
            case _:
                LOGGER.warning(f'Unknown message kind: {message.kind}')

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = ClientData(reader, writer)
        self.clients.add(client)

        while True:
            length_str = await reader.readexactly(5)
            length = int(length_str.decode()[:4], 16)

            raw_message_bytes = await reader.readexactly(length)
            raw_message = raw_message_bytes.decode()

            message = proto.Message.deserialize(raw_message)
            await self._process_message(message, client)

    async def listen(self) -> None:
        if self.server is None:
            raise RuntimeError('Server is not bound yet')

        async with self.server:
            await self.server.serve_forever()

    @property
    def host(self) -> str:
        return self._args.host

    @property
    def port(self) -> int:
        return self._args.port

    @property
    def debug(self) -> bool:
        return self._args.debug

    @property
    def loglevel(self) -> int:
        return logging.DEBUG if self.debug else logging.INFO

    @property
    def logfile(self) -> str:
        return self._args.logfile

    def __repr__(self) -> str:
        return f'ServerState(host={self.host}, port={self.port})'


def ensure_prerequisites() -> None:
    # required by logging
    if not os.path.exists('logs'):
        os.makedirs('logs')

    execute_migrations()


async def main() -> None:
    ensure_prerequisites()

    state = ServerState()
    await state.bind()
    await state.listen()

if __name__ == '__main__':
    dotenv.load_dotenv()

    asyncio.run(main())
