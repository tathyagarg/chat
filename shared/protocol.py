import enum
import json
from typing import Self

from pydantic import BaseModel


class MessageType(enum.StrEnum):
    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    ERROR = "ERROR"


class MessageKind(enum.StrEnum):
    CONNECT = "CONNECT"
    CONNECTED = "CONNECTED"

    DISCONNECT = "DISCONNECT"
    DISCONNECTED = "DISCONNECTED"

    MESSAGE = "MESSAGE"
    PROPAGATE = "PROPAGATE"


class UserMessage(BaseModel):
    username: str
    content: str
    timestamp: str

class Payload(BaseModel):
    @classmethod
    def empty(cls):
        return cls()

    @classmethod
    def from_data(cls, type_: MessageType, kind: MessageKind, data: dict):
        if type_ == MessageType.REQUEST:
            if kind == MessageKind.CONNECT:
                return ConnectRequestPayload(**data)
            elif kind == MessageKind.DISCONNECT:
                return DisconnectRequestPayload(**data)
            elif kind == MessageKind.MESSAGE:
                return MessageRequestPayload(**data)

        raise ValueError(f'Unknown message type/kind combination: {type_}/{kind}')

    @classmethod
    def create_payload(cls, type_: MessageType, kind: MessageKind, payload_str: str):
        if len(payload_str.strip()) == 0:
            return cls.empty()

        payload_data = json.loads(payload_str)
        return cls.from_data(type_, kind, payload_data)


class RequestPayload(Payload):
    pass


class ResponsePayload(Payload):
    success: bool
    error: str | None = None


class ConnectRequestPayload(RequestPayload):
    username: str
    password: str


class DisconnectRequestPayload(RequestPayload):
    pass


class MessageRequestPayload(RequestPayload):
    message: str


class ConnectedResponsePayload(ResponsePayload):
    user: str | None = None
    messages: list[UserMessage] | None = None


class DisconnectedResponsePayload(ResponsePayload):
    pass


class PropagateMessagePayload(Payload):
    message: UserMessage


class Message:
    """
    Expected format:
        [length, padded to 4 characters in hexadecimal]
        Type: <MessageType>
        Kind: <MessageKind>

        <payload>

    The length is the length of the message body (everything after the length field) in bytes. The length does not include the length field itself, nor the newline after it.
    """

    def __init__(self, type_, kind, payload):
        self.type = type_
        self.kind = kind

        self.payload: Payload = payload

    @classmethod
    def deserialize(cls, data: str) -> Self:
        type_str, kind_str, _, payload_str = data.split('\n', 3)

        if not type_str.startswith('Type:') or not kind_str.startswith('Kind:'):
            raise ValueError(f'Invalid message format: {data}')

        raw_type = type_str.split(':', 1)[1].strip()
        raw_kind = kind_str.split(':', 1)[1].strip()

        if raw_type not in MessageType.__members__:
            raise ValueError(f'Unknown message type: {raw_type}')

        if raw_kind not in MessageKind.__members__:
            raise ValueError(f'Unknown message kind: {raw_kind}')

        type_ = MessageType(raw_type)
        kind = MessageKind(raw_kind)

        payload = Payload.create_payload(type_, kind, payload_str)

        return cls(type_, kind, payload)

    def serialize(self) -> str:
        """Serializes the message to a string format as described in the class docstring."""

        payload = self.payload.model_dump_json()
        body = f'Type: {self.type}\nKind: {self.kind}\n\n{payload}'

        length = len(body.encode())
        length_str = f'{length:04x}'

        return f'{length_str}\n{body}'

