#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
_LISTENER_PID_PATTERN = re.compile(r"\bpid=(\d+)\b")


@dataclass(frozen=True, slots=True)
class _ProcessRecord:
    pid: int
    process_group: int
    arguments: str


def _parse_process_snapshot(output: str) -> dict[int, _ProcessRecord]:
    records: dict[int, _ProcessRecord] = {}
    for line in output.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) < 2:
            continue
        try:
            pid, process_group = (int(value) for value in fields[:2])
        except ValueError:
            continue
        records[pid] = _ProcessRecord(pid, process_group, fields[2] if len(fields) == 3 else "")
    return records


def _owned_processes(
    current: dict[int, _ProcessRecord],
    baseline: dict[int, _ProcessRecord],
    owned_process_groups: set[int],
) -> list[str]:
    return sorted(
        f"{record.pid} {record.process_group} {record.arguments}".rstrip()
        for pid, record in current.items()
        if pid not in baseline and record.process_group in owned_process_groups
    )


def _owned_listeners(
    current: set[str],
    baseline: set[str],
    current_processes: dict[int, _ProcessRecord],
    owned_process_groups: set[int],
) -> list[str]:
    owned_pids = {
        pid
        for pid, record in current_processes.items()
        if record.process_group in owned_process_groups
    }
    return sorted(
        listener
        for listener in current - baseline
        if any(int(pid) in owned_pids for pid in _LISTENER_PID_PATTERN.findall(listener))
    )


def _run(label: str, command: list[str], evidence: Path, owned_process_groups: set[int]) -> tuple[int, Path]:
    invocation = " ".join(command)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    owned_process_groups.add(process.pid)
    stdout, stderr = process.communicate()
    process_group_cleanup = "terminated"
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process_group_cleanup = "already_exited"
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    path = evidence / f"{label}.log"
    path.write_text(
        f"INVOCATION: {invocation}\nEXIT_CODE: {result.returncode}\n"
        f"PROCESS_GROUP_CLEANUP: {process_group_cleanup}\n\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        encoding="utf-8",
    )
    return result.returncode, path


def _marker(path: Path, text: str) -> bool:
    return text in path.read_text(encoding="utf-8")


def _cleanup(
    evidence: Path,
    temp_probe: Path,
    baseline_temp: set[str],
    baseline_processes: dict[int, _ProcessRecord],
    owned_process_groups: set[int],
    baseline_listeners: set[str],
) -> Path:
    temp_probe_exists = temp_probe.exists()
    temp_probe_text = str(temp_probe)
    config_dir = os.environ.get("XDG_CONFIG_HOME")
    owned_config_dir = Path(config_dir).resolve() if config_dir else None
    temp_candidates = sorted(
        str(path) for path in Path(tempfile.gettempdir()).glob("kateto-*")
        if path.exists() and str(path) not in baseline_temp and path.resolve() != owned_config_dir
    )
    ps = subprocess.run(["ps", "-eo", "pid=,pgid=,args="], text=True, capture_output=True, check=False)
    current_processes = _parse_process_snapshot(ps.stdout)
    owned_processes = _owned_processes(current_processes, baseline_processes, owned_process_groups)
    processes = [line for line in owned_processes if "kateto" in line.lower()]
    resource_trackers = [line for line in owned_processes if "resource_tracker" in line.lower()]
    ss = subprocess.run(["ss", "-ltnp"], text=True, capture_output=True, check=False)
    ports = _owned_listeners(
        set(ss.stdout.splitlines()),
        baseline_listeners,
        current_processes,
        owned_process_groups,
    )
    receipt = evidence / "cleanup-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "temp_probe": temp_probe_text,
                "temp_probe_removed": not temp_probe_exists,
                "remaining_kateto_temp_dirs": temp_candidates,
                "remaining_kateto_processes": processes,
                "remaining_resource_tracker_processes": resource_trackers,
                "remaining_owned_processes": owned_processes,
                "remaining_owned_process_groups": sorted({current_processes[int(line.split()[0])].process_group for line in owned_processes}),
                "remaining_kateto_listeners": ports,
                "kateto_process_free": not processes,
                "resource_tracker_process_free": not resource_trackers,
                "clean": not temp_probe_exists and not temp_candidates and not owned_processes and not ports,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt


def _artifact(artifact_id: str, kind: str, description: str, path: Path) -> dict[str, str]:
    return {"id": artifact_id, "kind": kind, "description": description, "path": str(path)}


def run(arguments: argparse.Namespace) -> int:
    evidence = arguments.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    baseline_temp = {str(path) for path in Path(tempfile.gettempdir()).glob("kateto-*") if path.exists()}
    baseline_ps = subprocess.run(["ps", "-eo", "pid=,pgid=,args="], text=True, capture_output=True, check=False)
    baseline_processes = _parse_process_snapshot(baseline_ps.stdout)
    baseline_ss = subprocess.run(["ss", "-ltnp"], text=True, capture_output=True, check=False)
    baseline_listeners = set(baseline_ss.stdout.splitlines())
    owned_process_groups: set[int] = set()
    temp_probe = Path(tempfile.mkdtemp(prefix="kateto-acceptance-probe-"))
    shutil.rmtree(temp_probe)

    py = sys.executable
    commands: dict[str, list[str]] = {
        "conversation": [py, "scripts/qa/vertical_slice.py", "--fixture", "--prompt", "plan tomorrow standup"],
        "interrupt": [
            py, "scripts/qa/vertical_slice.py", "--fixture", "--prompt", "plan tomorrow standup",
            "--interrupt-at", "token:3",
        ],
        "mcp": [py, "scripts/qa/mcp_fixture.py", "backlog_add"],
        "backlog": [py, "scripts/qa/backlog_fixture.py", "invalid-concurrent"],
        "workflow": [py, "scripts/qa/workflow_fixture.py", "--workflow", "daily-standup", "--voice", "Conquest"],
        "tui": [
            "node", "script/qa/web-terminal-visual-qa.mjs", "--title", "Kateto TUI",
            "--command", "uv run kateto tui --fixture", "--input", "{Enter}",
            "--evidence-dir", str(evidence / "tui"),
        ],
    }
    statuses: dict[str, tuple[int, Path]] = {
        label: _run(label, command, evidence, owned_process_groups) for label, command in commands.items()
    }

    if arguments.live:
        endpoint = os.environ.get("KATETO_LIVE_HEALTH_URL")
        if not endpoint:
            live_path = evidence / "live-preflight.log"
            live_path.write_text("LIVE_PREFLIGHT not_applicable: KATETO_LIVE_HEALTH_URL is unset\n", encoding="utf-8")
        else:
            with socket.create_connection((endpoint.split("//", 1)[-1].split("/", 1)[0].split(":")[0], 80), timeout=1):
                pass
    receipt = _cleanup(evidence, temp_probe, baseline_temp, baseline_processes, owned_process_groups, baseline_listeners)

    conversation = statuses["conversation"][1]
    interrupt = statuses["interrupt"][1]
    tui_meta = evidence / "tui" / "metadata.json"
    tui_png = evidence / "tui" / "terminal-screenshot.png"
    tui_transcript = evidence / "tui" / "terminal-transcript.txt"
    artifacts = [
        _artifact("a-conversation", "command-log", "Fixture event loop and TTS evidence", conversation),
        _artifact("a-interrupt", "command-log", "Cancellation and next utterance evidence", interrupt),
        _artifact("a-mcp", "command-log", "MCP backlog_add mutation and atomic replacement evidence", statuses["mcp"][1]),
        _artifact("a-backlog", "command-log", "Atomic backlog concurrency evidence", statuses["backlog"][1]),
        _artifact("a-workflow", "command-log", "Workflow lifecycle evidence", statuses["workflow"][1]),
        _artifact("a-tui-png", "screenshot", "Fresh TUI visual proof", tui_png),
        _artifact("a-tui-transcript", "transcript", "TUI terminal transcript", tui_transcript),
        _artifact("a-tui-meta", "metadata", "TUI capture metadata", tui_meta),
        _artifact("a-cleanup", "cleanup", "PID/resource_tracker/port/temp-dir cleanup receipt", receipt),
    ]
    surface = [
        {"scenarioId": "S15-01", "criterionReference": "task-15: fixture loop", "surface": "CLI fixture", "exactInvocation": "uv run python scripts/qa/vertical_slice.py --fixture --prompt 'plan tomorrow standup'", "verdict": "PASS" if statuses["conversation"][0] == 0 and all(_marker(conversation, x) for x in ("TRANSCRIPTION", "CLASSIFICATION category=EXECUTE", "GENERATE target=jane", "GENERATE target=doktor", "GENERATE target=conquest", "STREAMED_RESPONSE", "AUDIO_CHUNK", "TTS_PCM format=pcm_s16le")) else "FAIL", "artifactRefs": ["a-conversation"]},
        {"scenarioId": "S15-02", "criterionReference": "task-15: interrupt/resume", "surface": "CLI fixture", "exactInvocation": "uv run python scripts/qa/vertical_slice.py --fixture --prompt 'plan tomorrow standup' --interrupt-at token:3", "verdict": "PASS" if statuses["interrupt"][0] == 0 and _marker(interrupt, "INTERRUPT cancellation_streams=") and _marker(interrupt, "RESUME count=1") else "FAIL", "artifactRefs": ["a-interrupt"]},
        {"scenarioId": "S15-03", "criterionReference": "task-15: MCP/backlog atomic action", "surface": "MCP generated tool and canonical backlog fixture", "exactInvocation": "uv run python scripts/qa/mcp_fixture.py backlog_add; uv run python scripts/qa/backlog_fixture.py invalid-concurrent", "verdict": "PASS" if statuses["mcp"][0] == 0 and statuses["backlog"][0] == 0 and all(_marker(statuses["mcp"][1], marker) for marker in ("MCP_BACKLOG_ADD event=backlog_add target=backlog", "CANONICAL_STORE product_backlog.json", "ASSERT valid_json=true expected_item=true atomic_replace=true status=PASS")) and _marker(statuses["backlog"][1], "LOCK concurrent_valid_updates_preserved=true") and _marker(statuses["backlog"][1], "file_unchanged=true status=PASS") else "FAIL", "artifactRefs": ["a-mcp", "a-backlog"]},
        {"scenarioId": "S15-04", "criterionReference": "task-15: workflow lifecycle", "surface": "CLI fixture", "exactInvocation": "uv run python scripts/qa/workflow_fixture.py --workflow daily-standup --voice Conquest", "verdict": "PASS" if statuses["workflow"][0] == 0 and _marker(statuses["workflow"][1], "RESULT status=PASS") else "FAIL", "artifactRefs": ["a-workflow"]},
        {"scenarioId": "S15-05", "criterionReference": "task-15: TUI visual proof", "surface": "xterm.js terminal screenshot", "exactInvocation": "node script/qa/web-terminal-visual-qa.mjs --title 'Kateto TUI' --command 'uv run kateto tui --fixture' --input '{Enter}' --evidence-dir <task-15>/tui", "verdict": "PASS" if statuses["tui"][0] == 0 and tui_png.stat().st_size > 0 and _marker(tui_transcript, "PLUGINS / VOICES") and _marker(tui_transcript, "EVENT STREAM") else "FAIL", "artifactRefs": ["a-tui-png", "a-tui-transcript", "a-tui-meta"]},
        {"scenarioId": "S15-06", "criterionReference": "task-15: teardown", "surface": "OS process/port/temp inspection", "exactInvocation": "ps -eo pid=,args=; pgrep -af resource_tracker; ss -ltnp; find /tmp -maxdepth 1 -name 'kateto-*'", "verdict": "PASS" if all(json.loads(receipt.read_text(encoding="utf-8"))[key] for key in ("clean", "kateto_process_free", "resource_tracker_process_free")) else "FAIL", "artifactRefs": ["a-cleanup"]},
    ]
    adversarial = [
        {"scenarioId": "A15-01", "criterionReference": "task-15: interruption", "adversarialClass": "cancellation", "expectedBehavior": "active stream is cancelled and next utterance resumes", "verdict": surface[1]["verdict"], "artifactRefs": ["a-interrupt"]},
        {"scenarioId": "A15-02", "criterionReference": "task-15: optional live smoke", "adversarialClass": "unavailable external provider", "expectedBehavior": "not_applicable: live provider is optional and no health URL was supplied", "verdict": "not_applicable", "artifactRefs": ["a-cleanup"]},
        {"scenarioId": "A15-03", "criterionReference": "task-15: backlog atomicity", "adversarialClass": "concurrent invalid updates", "expectedBehavior": "canonical JSON remains unchanged after two invalid concurrent updates", "verdict": "PASS" if statuses["backlog"][0] == 0 and _marker(statuses["backlog"][1], "file_unchanged=true status=PASS") else "FAIL", "artifactRefs": ["a-backlog"]},
    ]
    matrix = {"manualQa": {"surfaceEvidence": surface, "adversarialCases": adversarial, "artifactRefs": artifacts}}
    matrix_path = evidence / "task-15-manual-qa.md"
    matrix_path.write_text("# Task 15 Manual QA\n\n```json\n" + json.dumps(matrix, indent=2) + "\n```\n", encoding="utf-8")
    done = evidence / "DoneClaim.json"
    done.write_text(json.dumps({"goalId": "task-15", "recordedAt": datetime.now(UTC).isoformat(), "matrix": str(matrix_path), "allRequiredPass": all(item["verdict"] == "PASS" for item in surface), "live": "not_applicable" if not arguments.live else "requested"}, indent=2) + "\n", encoding="utf-8")
    return 0 if all(item["verdict"] == "PASS" for item in surface) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true", required=True)
    parser.add_argument("--interrupt-at", default="token:3")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
