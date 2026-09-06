# Server

Entry point: `python -m server` (runs `server/__main__.py`'s `main()`).

## Modules

- **`server/__main__.py`** — CLI parsing, `ServerState` (the connection/event
  loop), and the per-message-kind request handlers.
- **`server/client_data.py`** — `ClientData`: per-connection state.
- **`server/database.py`** — migration runner and all MySQL queries.
- **`server/__init__.py`** — re-exports everything from `database.py`.

## CLI Arguments (`ServerState.__init__`)

| Flag | Default | Meaning |
|---|---|---|
| `--host`, `-H` | `localhost` | Interface to bind to. Use `0.0.0.0` to accept external connections. |
| `--port`, `-P` | `12345` | TCP port to bind to. |
| `--no-debug` | debug enabled | Disables debug mode: log level drops from `DEBUG` to `INFO`, and logs are no longer echoed to stdout (still written to the logfile). |
| `--logfile`, `-L` | `logs/server.log` | Log file path. The `logs/` directory is created automatically if missing (`ensure_prerequisites`). |

Environment variables (typically via a `.env` file, loaded with
`dotenv.load_dotenv()` before `main()` runs):

| Variable | Default | Purpose |
|---|---|---|
| `MYSQL_HOST` | `localhost` | MySQL host. |
| `MYSQL_PORT` | `3306` | MySQL port. |
| `MYSQL_USER` | `root` | MySQL user. |
| `MYSQL_PASSWORD` | *(empty)* | MySQL password. |
| `MYSQL_DATABASE` | `chat` | Database name. |

## Startup Sequence (`main()`)

1. `ensure_prerequisites()` — creates `logs/` if needed, then calls
   `execute_migrations()`, which connects to MySQL, ensures a `migrations`
   bookkeeping table exists, and applies any `.sql` file under `migrations/`
   that isn't already recorded as applied (in filename sort order).
2. `ServerState()` is constructed — parses CLI args, sets up logging, and opens
   a `mysql.connector.pooling.MySQLConnectionPool` (`pool_size=5`,
   `pool_name='chat_server_pool'`).
3. `state.bind()` — `asyncio.start_server` binds the socket and registers
   `_handle_client` as the per-connection callback.
4. `state.listen()` — `await self.server.serve_forever()`.

## Per-Connection Handling (`ServerState._handle_client`)

For each accepted connection:

1. A `ClientData(reader, writer)` is created and added to `self.clients`.
2. In a loop: read the 5-byte length prefix, read that many bytes, deserialize
   into a `proto.Message`, and pass it to `_process_message`.
3. `_process_message` ignores anything that isn't `MessageType.REQUEST`, then
   dispatches on `message.kind`:
   - `CONNECT` → `handle_request_connect`; on failure the client is dropped
     from `self.clients`.
   - `DISCONNECT` → `handle_request_disconnect`, then the loop breaks (closing
     the connection).
   - `MESSAGE` → `handle_request_message`.
   - anything else is logged and ignored.

Note that the read loop has no top-level exception handling around a client
disconnecting mid-read — an abrupt disconnect during `readexactly` will raise
inside `_handle_client` (asyncio will surface this as a task exception).

## `ClientData` (`server/client_data.py`)

Wraps a connection's `StreamReader`/`StreamWriter` plus:

- `addr` — the peer address, from `writer.get_extra_info('peername')`.
- `username` — `None` until authentication succeeds.
- `set_name(name)` — sets `username`; raises `ValueError` if a username is
  already set (whether it's the same name or a different one — re-`CONNECT`ing
  on an already-authenticated connection is not supported).
- `respond(message)` — serializes a `proto.Message` and writes it to the
  socket, draining the writer.

## Request Handlers (`server/__main__.py`)

### `handle_request_connect(message, sender, pool)`

1. Validates the payload is a `ConnectRequestPayload`.
2. Calls `database.authenticate_user` — this **creates the user if the
   username doesn't exist** (see below), so `CONNECT` doubles as registration.
3. On invalid credentials: sends an `ERROR`/`CONNECTED` response and returns
   `False` (caller removes the client from `self.clients`).
4. On success: calls `sender.set_name(...)` (can raise `ValueError` if already
   named — caught and reported as an `ERROR`/`CONNECTED`), fetches the 10 most
   recent messages via `fetch_recent_messages`, and responds with
   `RESPONSE`/`CONNECTED` including `user` and `messages`.

### `handle_request_disconnect(sender)`

Sends `RESPONSE`/`DISCONNECTED` with `success=True`, then closes the writer.
There is no failure path — this handler always reports success.

### `handle_request_message(message, sender, clients, pool)`

1. Validates the payload is a `MessageRequestPayload`.
2. Stores the message via `database.store_message`, using
   `sender.username or sender.addr` as the sender identifier (see the "Known
   Rough Edges" note in `ARCHITECTURE.md` about the fallback to `addr`).
3. Iterates a **copy** of `clients` (so concurrent disconnects don't break
   iteration) and, for each:
   - the sender gets a `RESPONSE`/`ACK`.
   - everyone else gets a `RESPONSE`/`PROPAGATE` containing a `UserMessage`.
   - if sending raises `ConnectionResetError`, `ConnectionAbortedError`, or
     `BrokenPipeError`, that client is logged and removed from `clients`.

## Database Layer (`server/database.py`)

| Function | Purpose |
|---|---|
| `all_migrations()` | Lists `migrations/*.sql` paths, sorted, relative to the repo root. |
| `execute_migrations()` | Applies any not-yet-applied migration, recording it in the `migrations` table after each successful run. |
| `create_user(conn, username, password)` | Hashes the password with `bcrypt` and inserts a new `users` row. |
| `authenticate_user(conn, username, password, create_if_not_exists=True)` | Looks up the user; if missing and `create_if_not_exists`, creates it and returns `True` (i.e. first login = signup); otherwise checks the bcrypt hash with `bcrypt.checkpw`. |
| `store_message(conn, username, message)` | Inserts into `messages`, resolving `sender_id` via a subquery on `users.username`. |
| `fetch_recent_messages(conn, limit=50)` | Joins `messages` to `users`, orders by `timestamp DESC`, returns up to `limit` rows as `proto.UserMessage` objects (note: descending order — most recent first — the client re-sorts before display, see `CLIENT.md`). |

Each handler in `__main__.py` acquires a pooled connection with
`pool.get_connection()` inside a `with` block, so connections are returned to
the pool automatically.

## Docker

`server/Dockerfile` builds a `python:3.13-slim` image, installs
`server/requirements.txt`, copies in `server/`, `shared/`, and `migrations/`,
exposes port `12345`, and runs `python -m server -H 0.0.0.0`.
`docker-compose.yml` pairs this with a `mysql:latest` container and wires up
the `MYSQL_*` environment variables from `.env`.
