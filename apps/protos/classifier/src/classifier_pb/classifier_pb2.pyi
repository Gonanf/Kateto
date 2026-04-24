from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Labels(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    talk: _ClassVar[Labels]
    think: _ClassVar[Labels]
talk: Labels
think: Labels

class BertRequest(_message.Message):
    __slots__ = ("prompt",)
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    prompt: str
    def __init__(self, prompt: _Optional[str] = ...) -> None: ...

class BertResponse(_message.Message):
    __slots__ = ("label",)
    LABEL_FIELD_NUMBER: _ClassVar[int]
    label: Labels
    def __init__(self, label: _Optional[_Union[Labels, str]] = ...) -> None: ...
