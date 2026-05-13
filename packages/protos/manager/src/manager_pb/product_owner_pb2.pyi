from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ProjectRequest(_message.Message):
    __slots__ = ("idea", "disponibility", "team", "description")
    IDEA_FIELD_NUMBER: _ClassVar[int]
    DISPONIBILITY_FIELD_NUMBER: _ClassVar[int]
    TEAM_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    idea: str
    disponibility: str
    team: _containers.RepeatedScalarFieldContainer[str]
    description: str
    def __init__(self, idea: _Optional[str] = ..., disponibility: _Optional[str] = ..., team: _Optional[_Iterable[str]] = ..., description: _Optional[str] = ...) -> None: ...

class ProjectResponse(_message.Message):
    __slots__ = ("stage", "message", "data_json", "markdown")
    STAGE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DATA_JSON_FIELD_NUMBER: _ClassVar[int]
    MARKDOWN_FIELD_NUMBER: _ClassVar[int]
    stage: str
    message: str
    data_json: str
    markdown: str
    def __init__(self, stage: _Optional[str] = ..., message: _Optional[str] = ..., data_json: _Optional[str] = ..., markdown: _Optional[str] = ...) -> None: ...
