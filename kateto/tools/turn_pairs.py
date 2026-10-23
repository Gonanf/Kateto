from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def process_lines(
    lines: Iterable[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Process JSONL lines, group turns by turn_end, and compute metrics."""
    turns = 0
    clean = 0
    client_blocked_count = 0
    legacy_no_pair = 0
    ambiguous_counts: dict[str, int] = {
        "multi_voice": 0,
        "no_output": 0,
        "no_input": 0,
    }
    dataset: list[dict[str, Any]] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue

        if not isinstance(rec, dict):
            continue

        event = rec.get("event")
        schema = rec.get("schema")

        if event == "turn_end" or schema == "turn/v1":
            turns += 1
            session_id = str(rec.get("session_id", ""))
            turn_id = str(rec.get("turn_id", ""))
            turn_input = str(rec.get("input", ""))
            outputs = rec.get("outputs") or []
            ambiguous = bool(rec.get("ambiguous", False))
            ambiguity = list(rec.get("ambiguity") or [])
            client_blocked = bool(rec.get("client_blocked", False))

            if client_blocked:
                client_blocked_count += 1

            # Tally ambiguity causes
            for cause in ambiguity:
                ambiguous_counts[cause] = ambiguous_counts.get(cause, 0) + 1

            if not ambiguous and not client_blocked and len(outputs) == 1:
                clean += 1
                out_item = outputs[0] if outputs else {}
                dataset.append({
                    "input": turn_input,
                    "output": str(out_item.get("text", "")),
                    "voice": str(out_item.get("voice", "")),
                    "session_id": session_id,
                    "turn_id": turn_id,
                })
        else:
            # Legacy lines without turn_id
            if "turn_id" not in rec or (
                rec.get("turn_id") is None and not rec.get("extra", {}).get("unsolicited", False)
            ):
                if event in ("user_turn", "voice_turn") or "event" not in rec:
                    legacy_no_pair += 1

    clean_pct = round((clean / turns) * 100, 1) if turns > 0 else 0.0

    report = {
        "turns": turns,
        "clean": clean,
        "clean_pct": clean_pct,
        "ambiguous": ambiguous_counts,
        "client_blocked": client_blocked_count,
        "legacy_no_pair": legacy_no_pair,
        # Mirrors for convenience
        "multi_voice": ambiguous_counts.get("multi_voice", 0),
        "no_output": ambiguous_counts.get("no_output", 0),
        "no_input": ambiguous_counts.get("no_input", 0),
    }

    return dataset, report


def process_files(
    file_paths: list[str | Path],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read one or more JSONL files and process turn records."""
    all_lines: list[str] = []
    for fp in file_paths:
        path = Path(fp)
        if not path.is_file():
            continue
        with open(path, "r", encoding="utf-8") as f:
            all_lines.extend(f.readlines())
    return process_lines(all_lines)


def write_dataset(dataset: list[dict[str, Any]], out_path: str | Path) -> None:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for pair in dataset:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")


def write_report(report: dict[str, Any], report_path: str | Path) -> None:
    p = Path(report_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruct turn pairs and report metrics from Kateto JSONL logs."
    )
    parser.add_argument("files", nargs="+", help="One or more JSONL log files")
    parser.add_argument("--out", type=str, default=None, help="Output dataset JSONL file")
    parser.add_argument("--report", type=str, default=None, help="Output report JSON file")

    args = parser.parse_args(argv)

    dataset, report = process_files(args.files)

    if args.out:
        write_dataset(dataset, args.out)

    if args.report:
        write_report(report, args.report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
