# Protocol

Defined in `shared/protocol.py`, exported via `shared/__init__.py`. Both
`server/__main__.py` and `client/__main__.py` import it as `shared.protocol` (or
`proto`).

## Framing

Every message on the wire has the shape:

```
[4-hex-digit length]\n
Type: <MessageType>\n
Kind: <MessageKind>\n
\n
<json payload>
```

- The length field is exactly 4 hex characters (zero-padded), followed by `\n` —
  5 bytes total. It is read first with `reader.readexactly(5)`.
- The length is the byte length of everything **after** the length field and its
  newline (i.e. the `Type:`/`Kind:`/blank-line/payload block), computed as
  `len(body.encode())` in `Message.serialize`.
- The remaining `length` bytes are read with `reader.readexactly(length)` and
  passed to `Message.deserialize`.
- `deserialize` splits on `\n` with `maxsplit=3`, giving `Type:` line, `Kind:`
  line, the blank separator line, and the raw JSON payload string.
- An empty/whitespace-only payload string deserializes to `Payload.empty()`
  (an empty base `Payload` instance) rather than attempting `json.loads`.

Because the max length field is 4 hex digits, a single message body cannot
exceed `0xFFFF` (65535) bytes.

## `MessageType`

`enum.StrEnum` with three values:

| Value | Meaning |
|---|---|
| `REQUEST` | Sent by the client to the server. |
| `RESPONSE` | Sent by the server to a client. |
| `ERROR` | Sent by the server to indicate a failed request (currently only used for a failed `CONNECT`). |

## `MessageKind`

| Value | Sent by | Meaning |
|---|---|---|
| `CONNECT` | client | Authenticate (log in or register) with a username/password. |
| `CONNECTED` | server | Result of a `CONNECT` request — success flag, username, and recent message history. |
| `DISCONNECT` | client | Politely close the connection. |
| `DISCONNECTED` | server | Acknowledges a `DISCONNECT`. |
| `MESSAGE` | client | A new chat message to broadcast. |
| `ACK` | server | Sent back to the *sender* of a `MESSAGE`, confirming it was stored. |
| `PROPAGATE` | server | Sent to every *other* connected client when a `MESSAGE` arrives. |

## Payload Types

All payloads are Pydantic `BaseModel`s rooted at `Payload`. `Payload.from_data`
maps a `(MessageType, MessageKind)` pair to the right subclass to parse
into — this is the single source of truth for which payload shape goes with
which type/kind combination. Unrecognized combinations raise `ValueError`.

### Requests (`RequestPayload` subclasses)

| Class | Fields | Used with |
|---|---|---|
| `ConnectRequestPayload` | `username: str`, `password: str` | `REQUEST` / `CONNECT` |
| `DisconnectRequestPayload` | *(none)* | `REQUEST` / `DISCONNECT` |
| `MessageRequestPayload` | `message: str` | `REQUEST` / `MESSAGE` |

### Responses (`ResponsePayload` subclasses, base has `success: bool`, `error: str | None`)

| Class | Extra fields | Used with |
|---|---|---|
| `ResponsePayload` | — | `RESPONSE` / `ACK`, and `ERROR` / `CONNECTED` (auth failure) |
| `ConnectedResponsePayload` | `user: str \| None`, `messages: list[UserMessage] \| None` | `RESPONSE` / `CONNECTED` |
| `DisconnectedResponsePayload` | — | `RESPONSE` / `DISCONNECTED` |

### Other

| Class | Fields | Used with |
|---|---|---|
| `PropagateMessagePayload` | `message: UserMessage` | `RESPONSE` / `PROPAGATE` |
| `UserMessage` | `username: str`, `content: str`, `timestamp: str` (ISO 8601) | embedded in `ConnectedResponsePayload.messages` and `PropagateMessagePayload.message` |

## Example Exchange

**Client → Server**, logging in:

```
Type: REQUEST
Kind: CONNECT

{"username": "alice", "password": "hunter2"}
```

**Server → Client**, success:

```
Type: RESPONSE
Kind: CONNECTED

{"success": true, "error": null, "user": "alice", "messages": [...]}
```

**Client → Server**, sending a chat message:

```
Type: REQUEST
Kind: MESSAGE

{"message": "hello world"}
```

**Server → sender**:

```
Type: RESPONSE
Kind: ACK

{"success": true, "error": null}
```

**Server → every other connected client**:

```
Type: RESPONSE
Kind: PROPAGATE

{"message": {"username": "alice", "content": "hello world", "timestamp": "2026-09-06T12:00:00"}}
```

Each of these bodies is prefixed with its 4-hex-digit length and a newline
before being sent, per the framing rules above.
