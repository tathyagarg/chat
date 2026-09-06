# Client

Entry point: `python -m client` (runs `client/__main__.py`'s `main()`). A
terminal UI built on [`rich`](https://github.com/Textualize/rich).

## `Server` (connection wrapper)

Thin wrapper around the `asyncio` stream reader/writer for the connection to
the chat server:

- `send(message)` — serializes a `proto.Message` and writes it, then drains.
- `receive()` — mirrors the server's framing logic: reads the 5-byte length
  prefix, reads the body, and deserializes it into a `proto.Message`.
- `disconnect(send_only=False)` — sends `REQUEST`/`DISCONNECT`. If
  `send_only` is `False` it also waits for and prints the
  `DISCONNECTED` response; if `True` (used during shutdown) it fires the
  request and returns immediately without waiting for a reply.

## `ClientState`

Tracks the local username and a single-slot "waiting for ACK" flag:

- `wait_for_ack()` — raises `RuntimeError` if already waiting (i.e. the
  previous message hasn't been acknowledged yet).
- `ack()` — raises `RuntimeError` if not currently waiting.

This means the client only supports one message in flight at a time — sending
a second message before the server ACKs the first will raise inside
`input_loop`.

## Startup Flow (`main()`)

1. Prompts for server host (default `localhost`) and port (default `12345`,
   validated as digits).
2. Opens the TCP connection and wraps it in a `Server`.
3. Registers a `SIGINT` handler that sets an `asyncio.Event` (`stop_event`)
   rather than killing the process directly, so shutdown can be graceful.
4. Calls `authenticate_user(server)`:
   - Prompts for username (`input`) and password (`getpass`, so it isn't
     echoed).
   - Sends `REQUEST`/`CONNECT` and awaits the response.
   - On success, returns `(messages, username)`; on failure, prints the error
     and `main()` exits.
5. Displays the returned message history, **sorted ascending by
   `timestamp`** (the server sends them most-recent-first; the client
   re-sorts before printing so history reads oldest → newest).
6. Spawns two concurrent tasks:
   - `input_loop(server, client)` — reads terminal input and sends messages.
   - `receive_loop(server, client)` — reads server messages and displays
     them.
7. Awaits `stop_event` (set by `Ctrl+C`); on trigger, cancels both tasks, calls
   `server.disconnect(send_only=True)`, and closes the writer.

## `input_loop`

Loops on `asyncio.to_thread(input, "")` (so blocking `input()` doesn't stall
the event loop). For each non-empty line:

1. Clears the just-typed line from the terminal (`\033[1A\033[2K`) — the
   message is about to be redrawn as a formatted panel instead.
2. Sends `REQUEST`/`MESSAGE` with the text.
3. Immediately renders the message locally via `display_message` (optimistic
   — it doesn't wait for the ACK to display it).
4. Calls `client.wait_for_ack()`.

## `receive_loop`

Loops on `server.receive()`. For each incoming message:

- `PropagateMessagePayload` → renders the embedded `UserMessage` via
  `display_message`.
- `ResponsePayload` (covers `ACK` and error responses) → if `success` is
  `False`, prints the error; either way, calls `client.ack()`.

## `display_message(message)`

Renders a `proto.UserMessage` as a `rich` `Panel`: the message content on top,
a right-aligned dimmed timestamp (parsed from ISO format and shown as
`DD Mon, YYYY HH:MM:SS`) below, and the sender's username as the panel title.

## Exiting

`Ctrl+C` is the only supported way to leave the client — it triggers the
`SIGINT` handler, which unblocks `stop_event`, cancels the input/receive
tasks, sends a fire-and-forget `DISCONNECT`, and closes the socket.
