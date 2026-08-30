import signal
import asyncio
from getpass import getpass

import shared.protocol as proto

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


async def authenticate_user(server) -> list[proto.UserMessage] | None:
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
        return message.payload.messages

    print(f"Authentication failed: {message.payload.error}")
    return


def display_message(message: proto.UserMessage) -> None:
    print(f"[{message.username}] {message.content}")


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
        messages = await authenticate_user(server)

        if not messages:
            print("Authentication failed. Exiting...")
            return

        for message in sorted(messages, key=lambda m: m.timestamp):
            display_message(message)

        await stop_event.wait()
    finally:
        print("\nDisconnecting from server...")

        await server.disconnect()

        server.writer.close()
        await server.writer.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())
