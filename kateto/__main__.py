from __future__ import annotations

import sys

import kateto.cli.commands as _commands  # noqa: F401  (register CLI commands)
from kateto.cli.app import KatetoApp


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        _ = KatetoApp().run(["--help"])
        return 0
    return KatetoApp().run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
