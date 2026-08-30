# Pyright keeps acting up about server.database and shared.protocol, even though they exist
# So, I'm muting the import errors for now
# pyright: reportMissingImports=false

import os
import logging
import asyncio
import argparse
import datetime

import mysql.connector
import dotenv

from server.client_data import ClientData
from server.database import execute_migrations, authenticate_user, fetch_recent_messages, store_message
import shared.protocol as proto
# from ..shared import protocol as proto

LOGGER = logging.getLogger(__name__)

#: The default port that the server binds onto when no port is specified
DEFAULT_PORT = 12345


async def handle_request_connect(
    message: proto.Message,
    sender: ClientData,
    pool: mysql.connector.pooling.MySQLConnectionPool
):
    if not isinstance(message.payload, proto.ConnectRequestPayload):
        raise ValueError('Invalid payload type for CONNECT message')

    try:
        with pool.get_connection() as conn:
            success = authenticate_user(conn, message.payload.username, message.payload.password)

            if not success:
                LOGGER.warning(f'Client {sender.addr} attempted to connect with invalid credentials: {message.payload.username}')

                await sender.respond(proto.Message(
                    type_=proto.MessageType.ERROR,
                    kind=proto.MessageKind.CONNECTED,
                    payload=proto.ResponsePayload(
                        success=False,
                        error='Invalid username or password'
                    )
                ))
                return

            sender.set_name(message.payload.username)
            LOGGER.info(f'Client {sender.addr} set their username to {sender.username}')

            recent = fetch_recent_messages(conn, limit=10)
            print(recent)

        await sender.respond(proto.Message(
            type_=proto.MessageType.RESPONSE,
            kind=proto.MessageKind.CONNECTED,
            payload=proto.ConnectedResponsePayload(
                success=True,
                user=sender.username,
                messages=recent
            )
        ))
    except ValueError as e:
        LOGGER.warning(f'Client {sender.addr} attempted to set their username to {message.payload.username}, but it was invalid: {e}')

        await sender.respond(proto.Message(
            type_=proto.MessageType.ERROR,
            kind=proto.MessageKind.CONNECTED,
            payload=proto.ResponsePayload(
                success=False,
                error=str(e)
            )
        ))


async def handle_request_disconnect(
    sender: ClientData
):
    LOGGER.info(f'Client {sender.addr} disconnected')
    await sender.respond(proto.Message(
        type_=proto.MessageType.RESPONSE,
        kind=proto.MessageKind.DISCONNECTED,
        payload=proto.ResponsePayload(
            success=True
        )
    ))

    sender.writer.close()
    await sender.writer.wait_closed()


async def handle_request_message(
    message: proto.Message,
    sender: ClientData,
    clients: set[ClientData],
    pool: mysql.connector.pooling.MySQLConnectionPool,
):
    if not isinstance(message.payload, proto.MessageRequestPayload):
        raise ValueError('Invalid payload type for MESSAGE message')

    received_at = datetime.datetime.now()

    with pool.get_connection() as conn:
        store_message(
            conn,
            sender.username or sender.addr,
            message.payload.message
        )

    for client in clients:
        if client is sender:
            await client.respond(proto.Message(
                type_=proto.MessageType.RESPONSE,
                kind=proto.MessageKind.ACK,
                payload=proto.ResponsePayload(
                    success=True
                )
            ))
        else:
            await client.respond(proto.Message(
                type_=proto.MessageType.RESPONSE,
                kind=proto.MessageKind.PROPAGATE,
                payload=proto.PropagateMessagePayload(
                    message=proto.UserMessage(
                        username=sender.username or sender.addr,
                        content=message.payload.message,
                        timestamp=received_at.isoformat()
                    )
                )
            ))


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
            database=os.getenv('MYSQL_DATABASE', 'chat')
        )

    async def bind(self) -> None:
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        LOGGER.info(f'Server bound to {self.host}:{self.port}')

    async def _process_message(
        self,
        message: proto.Message,
        sender: ClientData,
    ) -> bool:
        """
        Process a message from a client.
        Returns whether the server should continue listening to the client (True)
        or disconnect the client (False).
        """

        if message.type != proto.MessageType.REQUEST:
            LOGGER.warning(f'Ignoring non-request message from {sender.username or sender.addr}')
            return True

        match message.kind:
            case proto.MessageKind.CONNECT:
                await handle_request_connect(message, sender, self.db_pool)
            case proto.MessageKind.DISCONNECT:
                await handle_request_disconnect(sender)
                return False
            case proto.MessageKind.MESSAGE:
                await handle_request_message(message, sender, self.clients, self.db_pool)
            case _:
                LOGGER.warning(f'Unknown message kind: {message.kind}')

        return True

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = ClientData(reader, writer)
        self.clients.add(client)

        while True:
            length_str = await reader.readexactly(5)
            length = int(length_str.decode()[:4], 16)

            raw_message_bytes = await reader.readexactly(length)
            raw_message = raw_message_bytes.decode()

            message = proto.Message.deserialize(raw_message)
            maintain = await self._process_message(message, client)

            if not maintain:
                break

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
