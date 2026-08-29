"""Python bindings installation and compilation helper for Kateto.

Uses the Python bindings (pywhispercpp, llama-cpp-python) directly via their built-in
package mechanisms, passing hardware acceleration options (Vulkan, CUDA, CPU, Metal, OpenBLAS)
while strictly bounding parallel build jobs (CMAKE_BUILD_PARALLEL_LEVEL=1-2) to avoid OOM.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

AVAILABLE_BACKENDS = ("vulkan", "cuda", "cpu", "metal", "openblas")


@dataclass
class CompilerOptions:
    backend: str = "vulkan"
    cmake_args: list[str] = field(default_factory=list)
    jobs: int = 1  # Strictly limit parallel jobs to prevent OOM
    prefer_prebuilt: bool = True


def get_cmake_flags_for_backend(backend: str) -> list[str]:
    backend_lower = backend.lower()
    flags: list[str] = []
    match backend_lower:
        case "vulkan":
            flags.append("-DGGML_VULKAN=ON")
        case "cuda":
            flags.append("-DGGML_CUDA=ON")
        case "metal":
            flags.append("-DGGML_METAL=ON")
        case "openblas":
            flags.append("-DGGML_OPENBLAS=ON")
        case "cpu":
            flags.extend(["-DGGML_VULKAN=OFF", "-DGGML_CUDA=OFF"])
    return flags


def get_env_for_backend(backend: str, *, jobs: int = 1) -> dict[str, str]:
    """Return environment variables for compiling python bindings safely without OOM."""
    env = dict(os.environ)
    # Strictly limit compiler concurrency to avoid memory exhaustion (OOM)
    parallel_level = str(max(1, min(jobs, 2)))
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = parallel_level
    env["MAX_JOBS"] = parallel_level
    env["MAKEFLAGS"] = f"-j{parallel_level}"

    backend_lower = backend.lower()
    cmake_flags: list[str] = []
    match backend_lower:
        case "vulkan":
            env["GGML_VULKAN"] = "1"
            env["WHISPER_VULKAN"] = "1"
            cmake_flags.extend(["-DGGML_VULKAN=on", "-DWHISPER_VULKAN=on"])
        case "cuda":
            env["WHISPER_CUDA"] = "1"
            env["GGML_CUDA"] = "1"
            cmake_flags.append("-DGGML_CUDA=on")
        case "metal":
            env["GGML_METAL"] = "1"
            cmake_flags.append("-DGGML_METAL=on")
        case "openblas":
            env["GGML_OPENBLAS"] = "1"
            cmake_flags.append("-DGGML_OPENBLAS=on")
        case "cpu":
            cmake_flags.extend(["-DGGML_VULKAN=off", "-DGGML_CUDA=off"])

    if cmake_flags:
        existing = env.get("CMAKE_ARGS", "")
        env["CMAKE_ARGS"] = f"{existing} {' '.join(cmake_flags)}".strip()

    return env


def _run_installer(pkg_args: list[str], env: dict[str, str]) -> int:
    installer = ["uv", "pip", "install"] if shutil.which("uv") else [sys.executable, "-m", "pip", "install"]
    full_cmd = [*installer, *pkg_args]
    print(f"Running: {' '.join(full_cmd)}")
    res = subprocess.run(full_cmd, env=env, check=False)
    return res.returncode


def compile_whisper(
    options: CompilerOptions | None = None,
    *,
    work_dir: Path | None = None,
) -> int:
    del work_dir
    opts = options or CompilerOptions()
    env = get_env_for_backend(opts.backend, jobs=opts.jobs)
    if opts.cmake_args:
        existing = env.get("CMAKE_ARGS", "")
        env["CMAKE_ARGS"] = f"{existing} {' '.join(opts.cmake_args)}".strip()

    print(f"==> Installing pywhispercpp (backend: {opts.backend}, bounded parallel jobs: {env['CMAKE_BUILD_PARALLEL_LEVEL']})...")
    args = ["pywhispercpp"]
    if opts.backend in ("vulkan", "cuda"):
        args = ["--no-binary", "pywhispercpp", "--reinstall", "pywhispercpp"]

    return _run_installer(args, env)


def compile_llama(
    options: CompilerOptions | None = None,
    *,
    work_dir: Path | None = None,
) -> int:
    del work_dir
    opts = options or CompilerOptions()
    env = get_env_for_backend(opts.backend, jobs=opts.jobs)
    if opts.cmake_args:
        existing = env.get("CMAKE_ARGS", "")
        env["CMAKE_ARGS"] = f"{existing} {' '.join(opts.cmake_args)}".strip()

    print(f"==> Installing llama-cpp-python (backend: {opts.backend}, bounded parallel jobs: {env['CMAKE_BUILD_PARALLEL_LEVEL']})...")
    args = ["llama-cpp-python"]
    if opts.backend in ("vulkan", "cuda") and not opts.prefer_prebuilt:
        args.insert(0, "--no-binary=llama-cpp-python")

    return _run_installer(args, env)
