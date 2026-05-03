from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ProjectRequest(_message.Message):
    __slots__ = ("idea", "disponibility", "team")
    IDEA_FIELD_NUMBER: _ClassVar[int]
    DISPONIBILITY_FIELD_NUMBER: _ClassVar[int]
    TEAM_FIELD_NUMBER: _ClassVar[int]
    idea: str
    disponibility: str
    team: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, idea: _Optional[str] = ..., disponibility: _Optional[str] = ..., team: _Optional[_Iterable[str]] = ...) -> None: ...

class ProjectResponse(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...
