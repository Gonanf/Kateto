"""Compile all .proto files in each packages directory."""

import re
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd=None):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print("ERROR:", result.stdout)
        print(result.stderr, file=sys.stderr)
        print("With command:", " ".join(str(c) for c in cmd))
        sys.exit(1)
    return result


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
        if not proto_files:
            continue

        proto_names = [f.name for f in proto_files]
        pkg_name = f"{proto_dir.stem}-pb"
        module_name = f"{proto_dir.stem}_pb"

        # manager/src/manager_pb/
        py_src_dir = proto_dir / "src" / module_name
        py_src_dir.mkdir(parents=True, exist_ok=True)

        # Cleanup
        legacy_pyproject = proto_dir / "src" / "pyproject.toml"
        if legacy_pyproject.exists():
            legacy_pyproject.unlink()
            print(f"  Removed legacy {legacy_pyproject.relative_to(protos_root)}")

        legacy_init = proto_dir / "src" / "__init__.py"
        if legacy_init.exists():
            legacy_init.unlink()
            print(f"  Removed legacy {legacy_init.relative_to(protos_root)}")

        # Move any _pb2 files directly in src/ to the module directory
        src_dir = proto_dir / "src"
        for pattern in ("*_pb2.py", "*_pb2_grpc.py", "*_pb2.pyi"):
            for legacy_pb in src_dir.glob(pattern):
                target = py_src_dir / legacy_pb.name
                if not target.exists():
                    legacy_pb.rename(target)
                    print(
                        f"  Moved {legacy_pb.relative_to(protos_root)} -> {target.relative_to(protos_root)}"
                    )
                else:
                    legacy_pb.unlink()
                    print(f"  Removed duplicate {legacy_pb.relative_to(protos_root)}")

        cmd = [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            "-I",
            str(proto_dir),
            "--python_out",
            str(py_src_dir),
            "--pyi_out",
            str(py_src_dir),
            "--grpc_python_out",
            str(py_src_dir),
        ] + [str(f) for f in proto_files]

        print(
            f"Compiling {', '.join(proto_names)} in {proto_dir.relative_to(protos_root)}/"
        )
        run(cmd)

        init_file = py_src_dir / "__init__.py"
        init_content = ""
        for f in proto_files:
            stem = f.stem
            init_content += f"from .{stem}_pb2 import *\n"
            grpc_file = py_src_dir / f"{stem}_pb2_grpc.py"
            if grpc_file.exists():
                init_content += f"from .{stem}_pb2_grpc import *\n"
        init_file.write_text(init_content)
        print(f"  Updated {init_file.relative_to(protos_root)}")

        for grpc_file in py_src_dir.glob("*_pb2_grpc.py"):
            content = grpc_file.read_text()
            fixed = re.sub(
                r"^import (\w+_pb2) as (\w+__pb2)$",
                r"from . import \1 as \2",
                content,
                flags=re.MULTILINE,
            )
            if fixed != content:
                grpc_file.write_text(fixed)
                print(f"  Fixed imports in {grpc_file.relative_to(protos_root)}")

        pyproject_path = proto_dir / "pyproject.toml"
        if not pyproject_path.exists():
            pyproject_content = f"""[project]
name = "{pkg_name}"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["grpcio>=1.80.0"]

[build-system]
requires = ["uv_build>=0.11.7,<0.12.0"]
build-backend = "uv_build"
"""
            pyproject_path.write_text(pyproject_content)
            print(f"  Created {pyproject_path.relative_to(protos_root)}")
        else:
            existing = pyproject_path.read_text()
            if "[build-system]" not in existing:
                existing += '\n[build-system]\nrequires = ["uv_build>=0.11.7,<0.12.0"]\nbuild-backend = "uv_build"\n'
                pyproject_path.write_text(existing)
                print(f"  Updated {pyproject_path.relative_to(protos_root)}")

        ts_out_dir = proto_dir / "typescript"
        ts_out_dir.mkdir(exist_ok=True)

        for f in proto_files:
            cmd = [
                "bunx",
                "pbjs",
                "--ts",
                str(ts_out_dir / f"{f.stem}_pb.ts"),
                str(f),
            ]
            print(
                f"Compiling {f.name} to TypeScript in {proto_dir.relative_to(protos_root)}/"
            )
            run(cmd)

    print("Done.")


if __name__ == "__main__":
    main()
