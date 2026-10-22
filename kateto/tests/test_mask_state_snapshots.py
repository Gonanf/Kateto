from __future__ import annotations

import subprocess
import sys

import pytest

from kateto.mask.state_snapshots import (
    ListStateBackend,
    SnapshotStateError,
    TurnSnapshots,
    snapshot_cost,
)


def test_turn_start_snapshot_survives_live_state_mutation() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)
    initial_state = (1, 2)
    snapshots.begin_turn(initial_state)

    # When:
    snapshots.prefill_partial([3, 4])

    # Then:
    assert snapshots.turn_start == (1, 2)
    assert snapshots.state == (1, 2, 3, 4)


def test_correction_restores_turn_start_and_replays_only_corrected_tokens() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)
    snapshots.begin_turn((10, 20))
    snapshots.prefill_partial([99, 100])

    # When:
    result = snapshots.correct_partial([30, 40], at_ms=200.0)

    # Then:
    assert result.restored is True
    assert result.within_window is True
    assert result.replayed_tokens == 2
    assert snapshots.state == (10, 20, 30, 40)
    assert snapshots.turn_start == (10, 20)


def test_correction_within_budget_reports_estimated_ms() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(
        backend,
        prefill_token_budget=5,
        prefill_ms_per_token=0.8,
    )
    snapshots.begin_turn((1,))

    # When:
    result = snapshots.correct_partial([2, 3, 4], at_ms=100.0)

    # Then:
    assert result.within_budget is True
    assert result.replayed_tokens == 3
    assert pytest.approx(result.estimated_ms) == 2.4


def test_correction_after_window_is_ignored_and_state_untouched() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend, correction_window_ms=400.0)
    snapshots.begin_turn((1,))
    snapshots.prefill_partial([2, 3])

    # When:
    result = snapshots.correct_partial([99, 100], at_ms=450.0)

    # Then:
    assert result.within_window is False
    assert result.restored is False
    assert result.replayed_tokens == 0
    assert result.estimated_ms == 0.0
    assert snapshots.state == (1, 2, 3)


def test_correction_over_budget_flags_without_truncating() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend, prefill_token_budget=5)
    snapshots.begin_turn((1,))

    # When:
    tokens = [2, 3, 4, 5, 6, 7, 8]  # 7 tokens > budget 5
    result = snapshots.correct_partial(tokens, at_ms=200.0)

    # Then:
    assert result.within_budget is False
    assert result.replayed_tokens == 7
    assert snapshots.state == (1, 2, 3, 4, 5, 6, 7, 8)


def test_barge_in_does_not_return_to_turn_start() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)
    snapshots.begin_turn((1,))
    snapshots.prefill_partial([2])
    snapshots.begin_response()
    snapshots.note_emitted(10, audio_start_ms=100.0, audio_end_ms=200.0)
    snapshots.note_emitted(20, audio_start_ms=250.0, audio_end_ms=350.0)

    # When:
    res = snapshots.barge_in(cut_ms=150.0)

    # Then:
    assert res.state != snapshots.turn_start
    assert snapshots.turn_start == (1,)
    assert res.state == (1, 2, 10)


def test_barge_in_keeps_tokens_whose_audio_started_before_cut() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)
    snapshots.begin_turn((0,))
    snapshots.begin_response()
    snapshots.note_emitted(1, audio_start_ms=100.0, audio_end_ms=200.0)
    snapshots.note_emitted(2, audio_start_ms=200.0, audio_end_ms=300.0)

    # When: corte exacto en 200 ms (token 2 comenzo en 200 ms)
    res = snapshots.barge_in(cut_ms=200.0)

    # Then:
    assert res.kept_tokens == 2
    assert res.dropped_tokens == 0
    assert res.replayed_tokens == 2
    assert res.state == (0, 1, 2)


def test_barge_in_drops_tokens_whose_audio_starts_after_cut() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)
    snapshots.begin_turn((0,))
    snapshots.begin_response()
    snapshots.note_emitted(1, audio_start_ms=100.0, audio_end_ms=200.0)
    snapshots.note_emitted(2, audio_start_ms=300.0, audio_end_ms=400.0)
    snapshots.note_emitted(3, audio_start_ms=500.0, audio_end_ms=600.0)

    # When:
    res = snapshots.barge_in(cut_ms=250.0)

    # Then:
    assert res.kept_tokens == 1
    assert res.dropped_tokens == 2
    assert res.replayed_tokens == 1
    assert res.state == (0, 1)


def test_barge_in_with_nothing_played_equals_generation_base() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)
    snapshots.begin_turn((0,))
    snapshots.prefill_partial([1, 2])
    snapshots.begin_response()
    snapshots.note_emitted(3, audio_start_ms=100.0, audio_end_ms=200.0)

    # When: corte a los 50 ms antes de sonar ningun token
    res = snapshots.barge_in(cut_ms=50.0)

    # Then:
    assert res.kept_tokens == 0
    assert res.dropped_tokens == 1
    assert res.replayed_tokens == 0
    assert res.state == (0, 1, 2)


def test_barge_in_is_idempotent() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)
    snapshots.begin_turn((0,))
    snapshots.begin_response()
    snapshots.note_emitted(1, audio_start_ms=100.0, audio_end_ms=200.0)
    snapshots.note_emitted(2, audio_start_ms=300.0, audio_end_ms=400.0)

    # When:
    res1 = snapshots.barge_in(cut_ms=150.0)
    res2 = snapshots.barge_in(cut_ms=150.0)

    # Then:
    assert res1 == res2
    assert snapshots.state == res1.state


def test_begin_response_without_turn_raises() -> None:
    # Given:
    backend = ListStateBackend()
    snapshots = TurnSnapshots(backend)

    # When / Then:
    with pytest.raises(SnapshotStateError):
        snapshots.begin_response()


def test_memory_cost_matches_handoff() -> None:
    # Given:
    # When:
    r04 = snapshot_cost("0.4B", agents=4)
    r15 = snapshot_cost("1.5B", agents=4)

    # Then:
    assert r04.snapshots_per_agent == 2
    assert r04.per_agent_bytes == 3 * 1024 * 1024
    assert r04.total_bytes == 12 * 1024 * 1024

    assert r15.snapshots_per_agent == 2
    assert r15.per_agent_bytes == 12 * 1024 * 1024
    assert r15.total_bytes == 48 * 1024 * 1024

    with pytest.raises(ValueError, match="unknown_model"):
        snapshot_cost("unknown_model")


def test_module_imports_without_torch() -> None:
    # Given:
    cmd = [
        sys.executable,
        "-c",
        "import sys; import kateto.mask.state_snapshots; "
        "assert 'torch' not in sys.modules, 'torch no debe estar importado'",
    ]

    # When:
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Then:
    assert proc.returncode == 0, f"Error importando sin torch: {proc.stderr}"
