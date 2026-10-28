from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Sidecar:
    name: str
    adopt_if_healthy: bool
    required: bool
    health_url: str
    health_expect: str
    argv: tuple[str, ...]
    ready_timeout_s: int


@dataclass(frozen=True)
class Expose:
    name: str
    listen: str
    target: str
    health_url: str
    health_expect: str
    required: bool


@dataclass(frozen=True)
class Profile:
    host: str
    port: int
    token: str
    overrides: dict[str, Any]
    sidecars: tuple[Sidecar, ...]
    exposes: tuple[Expose, ...]


def load_profile(path: Path) -> Profile:
    if not path.is_file():
        raise ValueError(f"Hipotenusa profile not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        unknown = set(raw) - {"runtime", "sidecar", "expose"}
        if unknown:
            raise ValueError(f"unknown profile keys: {', '.join(sorted(unknown))}")
        runtime = raw["runtime"]
        if not isinstance(runtime, dict):
            raise ValueError("runtime must be a table")
        unknown = set(runtime) - {"host", "port", "token", "overrides"}
        if unknown:
            raise ValueError(f"unknown runtime keys: {', '.join(sorted(unknown))}")
        if "host" not in runtime or "port" not in runtime:
            raise ValueError("runtime requires host and port")
        overrides = runtime.get("overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError("runtime.overrides must be a table")

        def entries(section: str, cls: type[Any]) -> tuple[Any, ...]:
            values = raw.get(section, [])
            if not isinstance(values, list):
                raise ValueError(f"{section} must be an array of tables")
            expected = set(cls.__dataclass_fields__)
            for index, item in enumerate(values):
                if not isinstance(item, dict):
                    raise ValueError(f"{section}[{index}] must be a table")
                unknown_keys = set(item) - expected
                if unknown_keys:
                    raise ValueError(f"unknown {section} keys: {', '.join(sorted(unknown_keys))}")
            return tuple(cls(**item) for item in values)

        sidecars = entries("sidecar", Sidecar)
        exposes = entries("expose", Expose)
        return Profile(runtime["host"], runtime["port"], runtime.get("token", ""), overrides, sidecars, exposes)
    except (KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid Hipotenusa profile {path}: {exc}") from exc


def merge_overrides(raw: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    import copy
    result = copy.deepcopy(raw)
    for dotted, value in overrides.items():
        parts = dotted.split(".")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError(f"override path conflicts at {part}")
        node[parts[-1]] = value
    return result
