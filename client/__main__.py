"""
- The client is a Terminal User Interface (TUI) that sends requests to and reads responses from the server.
- The `rich`library is used to create the user interface (UI).
- The `getpass` module is used to securely read passwords from the user.
- `signal` module is used to handle termination signals (e.g., Ctrl+C) gracefully, i.e., to handle user exiting the application.
"""

import signal
import asyncio
import datetime
from getpass import getpass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import shared.protocol as proto  # type: ignore

console = Console()

class Server:
    """
    A class that represents a connection to the server.
    It provides methods to send and receive messages, as well as to disconnect from the server.
    """

    def __init__(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        """
        Connections to the server are composed of two "streams": a reader and a writer. A stream is like a file that you can read from or write to.
        The reader is used to read messages from the server, and the writer is used to send messages to the server.
        """
        self.reader = r
        self.writer = w


    async def send(self, message: proto.Message) -> None:
        """
        Send a message to the server. Serializes the message and writes it to the writer stream, then drains the writer to ensure the message is sent.
        1. Serializing: Serializing is the process of converting a data structure or object (in this case, a message) into a format that can be easily
           stored or transmitted (in this case, a string).

        2. Draining: Draining is the process of ensuring that all data written to a stream (in this case, the writer stream) has been sent and processed.
        """
        serialized = message.serialize()
        self.writer.write(serialized.encode())
        await self.writer.drain()


    async def receive(self) -> proto.Message:
        """
        Receive a message from the server. Reads the length of the message, then reads the message itself, and deserializes it into a Message object.
        1. Reading the length: By design of the protocol, the first 4 bytes of the message indicate the length of the message. This length is encoded
           in hexadecimal format, and is followed by a newline character. The `readexactly` method is used to read exactly 5 bytes from the reader stream,
           which includes the 4 bytes of length and the newline character.

        2. Decoding the length: The length is decoded from bytes to a string, and then converted from hexadecimal to an integer. The second parameter of
           the `int` function specifies that the string is in base 16 (hexadecimal).

        3. Reading the message: After reading the length, the `readexactly` method is used again to read the exact number of bytes specified by the length.

        4. Deserializing the message: The raw message is decoded from bytes to a string, and then deserialized into a Message object using the `deserialize`
           method of the Message class. Deserializing is the process of converting a string (in this case, the raw message) back into a data structure or
           object (in this case, a Message object). The message is returned to the caller of the `receive` method.
        """
        length_data = await self.reader.readexactly(5)
        length = int(length_data.decode()[:4], 16)

        raw_message_bytes = await self.reader.readexactly(length)
        raw_message = raw_message_bytes.decode()

        message = proto.Message.deserialize(raw_message)
        return message


    async def disconnect(self, send_only: bool = False) -> None:
        """
        Disconnect from the server. Sends a disconnect request to the server, and optionally waits for a response.
        1. Sending the disconnect request: A disconnect request message is created and sent to the server using the `send` method.

        2. Waiting for a response: If `send_only` is False, the client waits for a response from the server using the `receive` method. The response is
           checked to ensure it is a valid disconnect response. If the response indicates success, a message is printed to the console. If the response
           indicates failure, an error message is printed to the console.
        """
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
    """
    A class that represents the state of the client. It keeps track of the username and whether the client is waiting for an acknowledgment from the server.
    The client waits for an acknowledgment from the server after sending a message, to ensure that the message was received and processed by the server.
    """
    def __init__(self, username: str) -> None:
        self.username: str = username
        self.waiting_for_ack: bool = False


    def ack(self) -> None:
        """
        Acknowledge that the client has received an acknowledgment from the server. This method is called when the client receives a response from the server
        indicating that the message was received and processed. It sets the `waiting_for_ack` flag to False, indicating that the client is no longer waiting for
        an acknowledgment from the server. If the client is not waiting for an acknowledgment when this method is called, a RuntimeError is raised.
        """
        if not self.waiting_for_ack:
            raise RuntimeError("Not waiting for an ack")

        self.waiting_for_ack = False


    def wait_for_ack(self) -> None:
        """
        Set the `waiting_for_ack` flag to True, indicating that the client is now waiting for an acknowledgment from the server. This method is called after the
        client sends a message to the server, to indicate that the client is now waiting for a response from the server. If the client is already waiting for an
        acknowledgment when this method is called, a RuntimeError is raised.
        """
        if self.waiting_for_ack:
            raise RuntimeError("Already waiting for an ack")

        self.waiting_for_ack = True


async def authenticate_user(server) -> tuple[list[proto.UserMessage], str] | None:
    """
    Attempt to authenticate the user with the server. Prompts the user for a username and password, sends a connect request to the server, and waits for a response.
    If the authentication is successful, the server responds with a few recent messages and the username of the authenticated user. If the authentication fails, an
    error message is printed to the console. The function returns a tuple containing the list of recent messages and the username if authentication is successful,
    or None if authentication fails.

    1. Prompting for credentials: The user is prompted to enter a username and password. The `getpass` function is used to securely read the password without
       writing it to the console. Basically, the password is hidden when the user types it in.

    2. Sending the connect request: A connect request message is created with the entered username and password, and sent to the server using the `send` method.

    3. Waiting for a response: The client waits for a response from the server using the `receive` method. The response is checked to ensure it is a valid connected
       response. If the response indicates success, a message is printed to the console indicating that the user has been successfully authenticated, and the list of
       recent messages and the username are returned. If the response indicates failure, an error message is printed to the console, and None is returned.
    """
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
    """
    Display a message in the console. The message is displayed in a panel with the username as the title, the message content as the body, and the timestamp as 
    a dimmed footer.
    1. Formatting the timestamp: The timestamp of the message is converted from an ISO format string to a datetime object, and then formatted as a string in 
       the format "DD MMM, YYYY HH:MM:SS".

    2. Creating the message panel: A `rich` table is created. The first row contains the message content. The second row contains another table, which has a single
       column with the formatted timestamp. The message panel is created with the message table as the body, the username as the title, and the title aligned to 
       the left.

    3. Printing the message panel: The message panel is printed to the console using the `print` method of the `Console` class.
    """
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
    """
    Continuously read user input from the console, send it to the server, and display it in the console. The loop runs indefinitely until the program is terminated.
    1. Reading user input: The `input` function is used to read a line of input from the console. The `asyncio.to_thread` function is used to run the blocking `input`
       function in a separate thread, allowing the event loop to continue running while waiting for user input.

    2. Sending the message to the server: If the user input is not empty, a message is created with the user input as the content, and sent to the server 
       using the `send` method.

    3. Displaying the message in the console: The message is displayed in the console using the `display_message` function. The message is displayed with the 
       username of the client and the current timestamp.

    4. Waiting for acknowledgment: After sending the message to the server, the client waits for an acknowledgment from the server using the `wait_for_ack` method.
       This ensures that the message was received and processed by the server before allowing the user to send another message.
    """
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
    """
    Continuously receive messages from the server and display them in the console. The loop runs indefinitely until the program is terminated.
    1. Receiving messages from the server: The `receive` method of the `Server` class is used to receive messages from the server. The method blocks
       until a message is received, allowing the event loop to continue running while waiting for messages.

    2. Displaying messages in the console: If the received message is a propagate message, it is displayed in the console using the `display_message`
       function. If the received message is a response message, the success or error status is printed to the console, and the client acknowledges the
       response using the `ack` method.
    """
    while True:
        message = await server.receive()

        if isinstance(message.payload, proto.PropagateMessagePayload):
            display_message(message.payload.message)
        elif isinstance(message.payload, proto.ResponsePayload):
            if not message.payload.success:
                print(f"Error from server: {message.payload.error}")

            client.ack()


async def main():
    server = input("Enter server address (default: localhost:12345): ") or "localhost:12345"
    server_host, server_port = server.split(":") if ":" in server else (server, "12345")

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
