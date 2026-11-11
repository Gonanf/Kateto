from __future__ import annotations

import sys

import hipotenusa.cli.commands as _commands  # noqa: F401  (register CLI commands)
from hipotenusa.cli.app import HipotenusaApp


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        _ = HipotenusaApp().run(["--help"])
        return 0
    return HipotenusaApp().run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
