from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kateto.tools.compiler import (
    CompilerOptions,
    compile_llama,
    compile_whisper,
    get_cmake_flags_for_backend,
    get_env_for_backend,
)


def test_get_cmake_flags_for_backend():
    assert "-DGGML_VULKAN=ON" in get_cmake_flags_for_backend("vulkan")
    assert "-DGGML_CUDA=ON" in get_cmake_flags_for_backend("cuda")
    assert "-DGGML_METAL=ON" in get_cmake_flags_for_backend("metal")
    assert "-DGGML_OPENBLAS=ON" in get_cmake_flags_for_backend("openblas")
    cpu_flags = get_cmake_flags_for_backend("cpu")
    assert "-DGGML_VULKAN=OFF" in cpu_flags
    assert "-DGGML_CUDA=OFF" in cpu_flags


def test_get_env_for_backend():
    vulkan_env = get_env_for_backend("vulkan")
    assert vulkan_env.get("GGML_VULKAN") == "1"
    assert "-DGGML_VULKAN=on" in vulkan_env.get("CMAKE_ARGS", "")

    cuda_env = get_env_for_backend("cuda")
    assert cuda_env.get("WHISPER_CUDA") == "1"
    assert cuda_env.get("GGML_CUDA") == "1"
    assert "-DGGML_CUDA=on" in cuda_env.get("CMAKE_ARGS", "")


def test_compile_whisper_dry_run(tmp_path: Path):
    with patch("shutil.which", return_value="/usr/bin/uv"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            opts = CompilerOptions(backend="vulkan", jobs=1)

            # When: installing pywhispercpp
            code = compile_whisper(opts)

            # Then:
            assert code == 0
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            call_env = mock_run.call_args[1]["env"]
            assert "pywhispercpp" in call_args
            assert call_env["CMAKE_BUILD_PARALLEL_LEVEL"] == "1"
            assert call_env["GGML_VULKAN"] == "1"


def test_compile_llama_dry_run(tmp_path: Path):
    with patch("shutil.which", return_value="/usr/bin/uv"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            opts = CompilerOptions(backend="cuda", jobs=2)

            # When: installing llama-cpp-python
            code = compile_llama(opts)

            # Then:
            assert code == 0
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            call_env = mock_run.call_args[1]["env"]
            assert "llama-cpp-python" in call_args
            assert call_env["CMAKE_BUILD_PARALLEL_LEVEL"] == "2"
            assert "-DGGML_CUDA=on" in call_env["CMAKE_ARGS"]

