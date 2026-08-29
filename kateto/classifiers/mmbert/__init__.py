from __future__ import annotations

from typing import Any

__all__ = [
    "CATEGORIES",
    "PROTOTYPES",
    "PrototypeClassifier",
    "app",
    "main",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import server
        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
