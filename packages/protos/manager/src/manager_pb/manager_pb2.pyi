from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Agents(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TALKER: _ClassVar[Agents]
    DREAMER: _ClassVar[Agents]
    PRODUCT_OWNER: _ClassVar[Agents]
TALKER: Agents
DREAMER: Agents
PRODUCT_OWNER: Agents

class PromptRequest(_message.Message):
    __slots__ = ("text", "agent")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    AGENT_FIELD_NUMBER: _ClassVar[int]
    text: str
    agent: Agents
    def __init__(self, text: _Optional[str] = ..., agent: _Optional[_Union[Agents, str]] = ...) -> None: ...

class PromptResponse(_message.Message):
    __slots__ = ("token",)
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    token: str
    def __init__(self, token: _Optional[str] = ...) -> None: ...
