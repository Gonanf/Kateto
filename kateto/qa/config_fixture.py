from __future__ import annotations

import sys
from pathlib import Path


_DISALLOWED_CLI_CONFIG = """\
[kateto]
debug = false
hot_reload = false

[cli]
allowlist = ["rm"]
"""
_MALFORMED_TOML = "[kateto\ndebug = false\n"


def main() -> int:
    match sys.argv[1:]:
        case ["--config-dir", config_dir, "--mode", "disallowed-cli"]:
            _write_fixture(Path(config_dir), _DISALLOWED_CLI_CONFIG)
        case ["--config-dir", config_dir, "--mode", "malformed"]:
            _write_fixture(Path(config_dir), _MALFORMED_TOML)
        case _:
            print("usage: config_fixture --config-dir PATH --mode {disallowed-cli,malformed}", file=sys.stderr)
            return 2
    print(f"fixture written: {Path(config_dir) / 'config.toml'}")
    return 0


def _write_fixture(config_dir: Path, contents: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
