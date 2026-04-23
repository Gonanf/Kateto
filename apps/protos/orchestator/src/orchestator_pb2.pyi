from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class SpeechRequest(_message.Message):
    __slots__ = ("speech",)
    SPEECH_FIELD_NUMBER: _ClassVar[int]
    speech: str
    def __init__(self, speech: _Optional[str] = ...) -> None: ...

class SpeechResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
