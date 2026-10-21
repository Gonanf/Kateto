import os
import pathlib
import subprocess
import sys
import time

CLI = pathlib.Path(__file__).parent / "mask_servo_cli.py"


def test_sim_writes_one_line(tmp_path):
    sim_file = tmp_path / "sim.log"
    res = subprocess.run(
        [sys.executable, str(CLI), "--sim", str(sim_file), "--cmd", '{"jaw":45}'],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert sim_file.read_text(encoding="utf-8") == '{"jaw":45}\n'


def test_clamp_reported_and_written(tmp_path):
    sim_file = tmp_path / "sim.log"
    res = subprocess.run(
        [sys.executable, str(CLI), "--sim", str(sim_file), "--cmd", '{"jaw":200}'],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "clamped" in res.stderr
    assert sim_file.read_text(encoding="utf-8") == '{"jaw":85}\n'


def test_malformed_exit3_no_write(tmp_path):
    sim_file = tmp_path / "sim.log"
    res = subprocess.run(
        [sys.executable, str(CLI), "--sim", str(sim_file), "--cmd", '{"jaw":}'],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 3
    assert not sim_file.exists() or sim_file.read_text(encoding="utf-8") == ""


def test_script_no_wait(tmp_path):
    sim_file = tmp_path / "sim.log"
    script_file = tmp_path / "test.script"
    script_file.write_text(
        "# Script de prueba\n"
        "@500\n"
        '{"jaw":30}\n'
        "@500\n"
        '{"eye_x":90}\n',
        encoding="utf-8",
    )

    t0 = time.time()
    res = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--sim",
            str(sim_file),
            "--script",
            str(script_file),
            "--no-wait",
        ],
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - t0

    assert res.returncode == 0
    assert elapsed < 2.0
    lines = sim_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert lines[0] == '{"jaw":30}'
    assert lines[1] == '{"eye_x":90}'


def test_port_without_pyserial(tmp_path):
    fake_lib = tmp_path / "fake_lib"
    fake_lib.mkdir()
    (fake_lib / "serial.py").write_text("raise ImportError('no serial')\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": f"{fake_lib}:" + os.environ.get("PYTHONPATH", "")}
    res = subprocess.run(
        [sys.executable, str(CLI), "--port", "/dev/null", "--cmd", '{"jaw":45}'],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 2
    assert "pyserial no instalado" in res.stderr


def test_help():
    res = subprocess.run(
        [sys.executable, str(CLI), "--help"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "mask_servo_cli.py" in res.stdout or "usage:" in res.stdout
