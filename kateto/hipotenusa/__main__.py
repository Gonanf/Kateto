from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import load_profile
from .supervisor import health, run


def main() -> int:
    parser = argparse.ArgumentParser(prog="hipotenusa")
    parser.add_argument("--profile", type=Path, default=Path.home() / ".config/kateto/hipotenusa.toml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile)
        if args.dry_run:
            for item in profile.sidecars:
                print(f"sidecar {item.name} {item.health_url}")
            for item in profile.exposes:
                print(f"expose {item.name} {item.listen} -> {item.target} {item.health_url}")
            print(f"runtime http {profile.host}:{profile.port}")
            return 0
        asyncio.run(run(profile, json_output=args.json))
        return 0
    except Exception as exc:
        parser.exit(1, f"hipotenusa: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
