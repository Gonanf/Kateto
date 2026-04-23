"""Compile all .proto files in each packages directory."""

import subprocess
import sys
from pathlib import Path


def compile(cmd, proto_dir, out_dir, protos_root):

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR compiling {proto_dir}:", result.stdout)
        print(result.stderr, file=sys.stderr)
        print("With command:", " ".join(cmd))
        sys.exit(1)

    print(f"  → {out_dir.relative_to(protos_root)}/")


def main():
    protos_root = Path(__file__).parent

    proto_dirs = set()
    for proto_file in protos_root.rglob("*.proto"):
        proto_dirs.add(proto_file.parent)

    if not proto_dirs:
        print("No .proto files found.")
        sys.exit(0)

    for proto_dir in sorted(proto_dirs):
        proto_files = list(proto_dir.glob("*.proto"))
        proto_names = [f.name for f in proto_files]

        out_dir = proto_dir / "src" / proto_dir.stem
        out_dir.mkdir(exist_ok=True)

        cmd = [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            "-I",
            str(proto_dir),
            "--python_out",
            str(out_dir),
            "--pyi_out",
            str(out_dir),
            "--grpc_python_out",
            str(out_dir),
        ] + [str(f) for f in proto_files]
        print(
            f"Compiling {', '.join(proto_names)} in {proto_dir.relative_to(protos_root)}/"
        )

        compile(cmd, proto_dir, out_dir, protos_root)

        for f in proto_files:
            cmd = [
                "uv",
                "init",
                "--name",
                str(f.stem + "_pb"),
                "--bare",
                "--lib",
                str(out_dir),
            ]

            compile(cmd, proto_dir, out_dir, protos_root)
            cmd = ["touch", str(out_dir / "__init__.py")]
            compile(cmd, proto_dir, out_dir, protos_root)

        out_dir = proto_dir / "typescript"
        out_dir.mkdir(exist_ok=True)

        cmd = [
            [
                "bunx",
                "pbjs",
                "--ts",
                str(out_dir / Path(f.stem + "_pb.ts")),
                str(f),
            ]
            for f in proto_files
        ]

        for c in cmd:
            print(
                f"Compiling {', '.join(proto_names)} in {proto_dir.relative_to(protos_root)}/"
            )

            compile(c, proto_dir, out_dir, protos_root)

    print("Done.")


if __name__ == "__main__":
    main()
