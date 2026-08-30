import signal
import asyncio
import datetime
from getpass import getpass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import shared.protocol as proto

console = Console()

class Server:
    def __init__(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        self.reader = r
        self.writer = w


    async def send(self, message: proto.Message) -> None:
        serialized = message.serialize()
        self.writer.write(serialized.encode())
        await self.writer.drain()


    async def receive(self) -> proto.Message:
        length_data = await self.reader.readexactly(5)
        length = int(length_data.decode()[:4], 16)

        raw_message_bytes = await self.reader.readexactly(length)
        raw_message = raw_message_bytes.decode()

        message = proto.Message.deserialize(raw_message)
        return message


    async def disconnect(self, send_only: bool = False) -> None:
        message = proto.Message(
            type_=proto.MessageType.REQUEST,
            kind=proto.MessageKind.DISCONNECT,
            payload=proto.DisconnectRequestPayload()
        )

        await self.send(message)

        if not send_only:
            response = await self.receive()
            if not isinstance(response.payload, proto.DisconnectedResponsePayload):
                print("Invalid response from server.")
                return

            if response.payload.success:
                print("Disconnected from server.")
            else:
                print(f"Failed to disconnect: {response.payload.error}")


class ClientState:
    def __init__(self, username: str) -> None:
        self.username: str = username
        self.waiting_for_ack: bool = False


    def ack(self) -> None:
        if not self.waiting_for_ack:
            raise RuntimeError("Not waiting for an ack")

        self.waiting_for_ack = False


    def wait_for_ack(self) -> None:
        if self.waiting_for_ack:
            raise RuntimeError("Already waiting for an ack")

        self.waiting_for_ack = True

async def authenticate_user(server) -> tuple[list[proto.UserMessage], str] | None:
    username = input("Enter username: ")
    password = getpass("Enter password: ")

    message = proto.Message(
        type_=proto.MessageType.REQUEST,
        kind=proto.MessageKind.CONNECT,
        payload=proto.ConnectRequestPayload(
            username=username,
            password=password
        )
    )
    await server.send(message)
    message = await server.receive()

    if not isinstance(message.payload, proto.ConnectedResponsePayload):
        print("Invalid response from server.")
        return

    if message.payload.success:
        print(f"Successfully authenticated as {message.payload.user}.")
        return message.payload.messages or [], username

    print(f"Authentication failed: {message.payload.error}")
    return


def display_message(message: proto.UserMessage) -> None:
    msg_time = datetime.datetime.fromisoformat(message.timestamp)
    formatted_time = msg_time.strftime("%d %b, %Y %H:%M:%S")

    table = Table.grid(expand=True)
    table.add_row(message.content)

    date_table = Table.grid(expand=True)
    date_table.add_column(justify="right")
    date_table.add_row(f"[dim]{formatted_time}[/dim]")

    table.add_row(date_table)

    console.print(
        Panel(
            table,
            title=f"[bold italic cyan][ {message.username} ][/bold italic cyan]",
            title_align='left',
            expand=True,
        )
    )


async def input_loop(server: Server, client: ClientState) -> None:
    while True:
        user_input = await asyncio.to_thread(input, "")
        print("\033[1A\033[2K", end="")

        if len(user_input.strip()) == 0:
            continue

        message = proto.Message(
            type_=proto.MessageType.REQUEST,
            kind=proto.MessageKind.MESSAGE,
            payload=proto.MessageRequestPayload(
                message=user_input
            )
        )
        await server.send(message)

        display_message(proto.UserMessage(
            username=client.username,
            content=user_input,
            timestamp=datetime.datetime.now().isoformat()
        ))

        client.wait_for_ack()


async def receive_loop(server: Server, client: ClientState) -> None:
    while True:
        message = await server.receive()

        if isinstance(message.payload, proto.PropagateMessagePayload):
            display_message(message.payload.message)
        elif isinstance(message.payload, proto.ResponsePayload):
            if not message.payload.success:
                print(f"Error from server: {message.payload.error}")

            client.ack()


async def main():
    server_host = input("Enter server host (default: localhost): ") or "localhost"
    server_port = (input("Enter server port (default: 12345): ") or "12345").strip()

    if not server_port.isdigit():
        print("Invalid port number. Exiting...")
        return

    r, w = await asyncio.open_connection(server_host, int(server_port))
    server = Server(r, w)

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    loop.add_signal_handler(signal.SIGINT, stop_event.set)

    try:
        resp = await authenticate_user(server)
        if not resp:
            print("Authentication failed. Exiting...")
            return

        messages, username = resp
        client = ClientState(username)

        for message in sorted(messages, key=lambda m: m.timestamp):
            display_message(message)

        input_task = asyncio.create_task(input_loop(server, client))
        receive_task = asyncio.create_task(receive_loop(server, client))

        try:
            await stop_event.wait()
        finally:
            input_task.cancel()
            receive_task.cancel()

    finally:
        print("\nDisconnecting from server...")

        await server.disconnect(send_only=True)

        server.writer.close()
        await server.writer.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())
