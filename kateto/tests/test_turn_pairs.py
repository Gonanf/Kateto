from __future__ import annotations

import json
from pathlib import Path

from kateto.tools.turn_pairs import main, process_files, process_lines


def test_sample_session_report_and_out(tmp_path):
    fixture_path = (
        Path(__file__).parent / "fixtures" / "turn_pairs" / "sample-session.jsonl"
    )
    assert fixture_path.exists(), f"fixture not found at {fixture_path}"

    out_path = tmp_path / "pairs.jsonl"
    report_path = tmp_path / "report.json"

    ret = main([
        str(fixture_path),
        "--out",
        str(out_path),
        "--report",
        str(report_path),
    ])
    assert ret == 0

    # Verify report
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["turns"] == 10
    assert report["clean"] == 6
    assert report["clean_pct"] == 60.0
    assert report["ambiguous"]["multi_voice"] == 2
    assert report["ambiguous"]["no_output"] == 1
    assert report["ambiguous"]["no_input"] == 1
    assert report["multi_voice"] == 2
    assert report["no_output"] == 1
    assert report["client_blocked"] == 0
    assert report["legacy_no_pair"] == 0

    # Verify dataset pairs in --out
    lines = [
        json.loads(line)
        for line in out_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 6
    # No pair for the turn sin output (turn-09)
    assert not any(p["turn_id"] == "turn-09" for p in lines)
    # Only clean turns (turn-01 to turn-06)
    expected_turn_ids = {f"turn-0{i}" for i in range(1, 7)}
    assert {p["turn_id"] for p in lines} == expected_turn_ids


def test_legacy_and_client_blocked_lines():
    raw_lines = [
        # Legacy lines without turn_id
        json.dumps({"event": "user_turn", "text": "linea vieja", "voice": "user"}),
        json.dumps({"event": "voice_turn", "text": "respuesta vieja", "voice": "jane"}),
        # Client blocked turn_end
        json.dumps({
            "schema": "turn/v1",
            "event": "turn_end",
            "session_id": "s1",
            "turn_id": "t-blocked",
            "input": "consulta privada",
            "outputs": [{"voice": "jane", "text": "resp", "sequence_first": 0, "sequence_last": 0}],
            "ambiguous": False,
            "ambiguity": [],
            "client_blocked": True,
        }),
    ]
    dataset, report = process_lines(raw_lines)
    assert report["turns"] == 1
    assert report["client_blocked"] == 1
    assert report["clean"] == 0
    assert report["legacy_no_pair"] == 2
    assert len(dataset) == 0
