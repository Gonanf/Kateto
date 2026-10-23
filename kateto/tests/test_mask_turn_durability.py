import pytest

from kateto.mask.turn_durability import (
    TurnDurabilityMetrics,
    TurnJournal,
)


def test_stamp_asigna_seq_y_turn_id_monotonicos():
    # Given: a fresh TurnJournal.
    journal = TurnJournal()
    payload = {"event": "audio_output", "audio": "base64data"}

    # When: stamping three sequential frames without final.
    f1 = journal.stamp(payload, final=False)
    f2 = journal.stamp(payload, final=False)
    f3 = journal.stamp(payload, final=False)

    # Then: seq increments monotonically starting at 1, turn_id is 1.
    assert f1["seq"] == 1 and f1["turn_id"] == 1
    assert f2["seq"] == 2 and f2["turn_id"] == 1
    assert f3["seq"] == 3 and f3["turn_id"] == 1

    # Then: original payload was not mutated.
    assert "seq" not in payload and "turn_id" not in payload

    # Then: journal properties match.
    assert journal.first_seq == 1
    assert journal.last_seq == 3
    assert journal.turn_id == 1


def test_final_sube_turn_id_en_el_frame_siguiente():
    # Given: a fresh TurnJournal.
    journal = TurnJournal()

    # When: stamping frame 1 (not final), frame 2 (final), and frame 3 (next turn).
    f1 = journal.stamp({"chunk": 1}, final=False)
    f2 = journal.stamp({"chunk": 2}, final=True)
    assert journal.turn_id == 1

    f3 = journal.stamp({"chunk": 3}, final=False)

    # Then: turn_id only increments on the frame stamped AFTER final=True.
    assert f1["seq"] == 1 and f1["turn_id"] == 1
    assert f2["seq"] == 2 and f2["turn_id"] == 1
    assert f3["seq"] == 3 and f3["turn_id"] == 2
    assert journal.turn_id == 2


def test_resume_devuelve_solo_los_frames_posteriores_al_after_seq():
    # Given: a journal with 5 frames.
    journal = TurnJournal()
    for i in range(1, 6):
        journal.stamp({"idx": i}, final=False)

    # When: client requests resume after seq 2.
    batch = journal.resume(after_seq=2)

    # Then: only frames with seq > 2 are returned, ascending by seq.
    assert [f["seq"] for f in batch.frames] == [3, 4, 5]
    assert batch.after_seq == 2
    assert batch.gap is False
    assert batch.turn_id == 1


def test_resume_con_after_seq_igual_al_ultimo_no_devuelve_frames():
    # Given: a journal with 4 frames.
    journal = TurnJournal()
    for i in range(1, 5):
        journal.stamp({"idx": i}, final=False)

    # When: client requests resume with after_seq equal to last_seq (4).
    batch = journal.resume(after_seq=4)

    # Then: frames list is empty, gap is False.
    assert batch.frames == []
    assert batch.gap is False
    assert batch.after_seq == 4
    assert batch.turn_id == 1


def test_resume_reporta_gap_cuando_el_after_seq_quedo_fuera_de_retencion():
    # Given: a journal with max_frames=3, where 6 frames were stamped.
    journal = TurnJournal(max_frames=3)
    for i in range(1, 7):
        journal.stamp({"idx": i}, final=False)

    # Retained frames are [4, 5, 6]; first_seq is 4.
    assert journal.first_seq == 4

    # When: client requests resume after seq 2 (seq 3 was evicted).
    batch = journal.resume(after_seq=2)

    # Then: gap is reported as True and only retained frames are returned.
    assert batch.gap is True
    assert [f["seq"] for f in batch.frames] == [4, 5, 6]


def test_retencion_por_max_frames_descarta_los_mas_viejos():
    # Given: a journal with capacity for 3 frames.
    journal = TurnJournal(max_frames=3)

    # When: stamping 5 frames.
    for i in range(1, 6):
        journal.stamp({"idx": i}, final=False)

    # Then: oldest 2 frames are dropped, stats reflect retention.
    st = journal.stats()
    assert st["frames"] == 3
    assert st["dropped"] == 2
    assert journal.first_seq == 3
    assert journal.last_seq == 5


def test_retencion_por_bytes_descarta_los_mas_viejos():
    # Given: a journal with capacity for 1000 bytes.
    journal = TurnJournal(max_bytes=1000)

    # When: stamping 3 frames of 400 bytes each.
    journal.stamp({"audio": "a" * 400}, final=False, n_bytes=400)
    journal.stamp({"audio": "b" * 400}, final=False, n_bytes=400)
    journal.stamp({"audio": "c" * 400}, final=False, n_bytes=400)

    # Then: oldest frame is discarded to stay under 1000 bytes.
    st = journal.stats()
    assert st["frames"] == 2
    assert st["bytes"] == 800
    assert st["dropped"] == 1
    assert journal.first_seq == 2
    assert journal.last_seq == 3


def test_no_pierde_audio_del_turno_en_curso_con_caida_a_la_mitad():
    # Given: a journal where 4 frames constitute turn 1.
    journal = TurnJournal()
    f1 = journal.stamp({"audio": "chunk1"}, final=False)
    f2 = journal.stamp({"audio": "chunk2"}, final=False)

    # When: connection drops after client received seq 2, while backend continues emitting.
    f3 = journal.stamp({"audio": "chunk3", "final": False}, final=False)
    f4 = journal.stamp({"audio": "chunk4", "final": True}, final=True)

    # And when: client reconnects asking for frames after seq 2.
    batch = journal.resume(after_seq=2)

    # Then: client receives exactly the remaining frames without gap.
    assert [f["seq"] for f in batch.frames] == [3, 4]
    assert batch.gap is False
    assert batch.frames[-1]["final"] is True
    assert [f1["seq"], f2["seq"], *[f["seq"] for f in batch.frames]] == [1, 2, 3, 4]


def test_metricas_survived_pct_sin_turnos_es_cero():
    # Given: a fresh metrics tracker.
    metrics = TurnDurabilityMetrics()

    # When / Then: survived_pct is 0.0 and snapshot reflects 0.0.
    assert metrics.survived_pct == 0.0
    snap = metrics.snapshot()
    assert snap["survived_pct"] == 0.0
    assert snap["turns_started"] == 0


def test_metricas_survived_pct_cuenta_sobrevividos_y_perdidos():
    # Given: a metrics tracker with 3 started turns.
    metrics = TurnDurabilityMetrics()
    metrics.start_turn()
    metrics.finish_turn(survived=True)
    metrics.start_turn()
    metrics.finish_turn(survived=True)
    metrics.start_turn()
    metrics.finish_turn(survived=False)

    # When: evaluating statistics.
    snap = metrics.snapshot()

    # Then: survived_pct is 66.7% (2 / 3).
    assert snap["turns_started"] == 3
    assert snap["turns_survived"] == 2
    assert snap["turns_lost"] == 1
    assert snap["survived_pct"] == 66.7


@pytest.mark.parametrize("outage_at", [1, 2, 3, 4, 5, 6])
def test_matriz_de_caidas_sobrevive_100_por_ciento(outage_at: int):
    # Given: a journal and metrics tracker for a 6-frame turn.
    journal = TurnJournal()
    metrics = TurnDurabilityMetrics()
    metrics.start_turn()
    frames = [
        journal.stamp({"audio": f"chunk_{i}"}, final=(i == 6))
        for i in range(1, 7)
    ]

    # When: stamps 1..outage_at are delivered and socket disconnects.
    _delivered = frames[:outage_at]
    metrics.disconnect()

    # And when: client reconnects and resumes from outage_at.
    batch = journal.resume(outage_at)

    # Then: replayed frames are exactly outage_at + 1 .. 6.
    expected_seqs = list(range(outage_at + 1, 7))
    assert [f["seq"] for f in batch.frames] == expected_seqs

    # And when: metrics record replay and finish turn.
    metrics.resume(replayed=len(batch.frames), gap=batch.gap)
    metrics.finish_turn(survived=True)

    # Then: 100.0% survived, no gap.
    assert metrics.survived_pct == 100.0
    assert batch.gap is False


def test_resume_es_idempotente():
    # Given: a journal with 5 frames.
    journal = TurnJournal()
    for i in range(1, 6):
        journal.stamp({"idx": i}, final=False)

    # When: calling resume with the same after_seq multiple times.
    batch1 = journal.resume(2)
    batch2 = journal.resume(2)

    # Then: both calls yield identical seq lists, gap, and turn_id.
    assert [f["seq"] for f in batch1.frames] == [f["seq"] for f in batch2.frames] == [3, 4, 5]
    assert batch1.gap == batch2.gap is False
    assert batch1.turn_id == batch2.turn_id == 1


def test_clear_resetea_seq_y_stats():
    # Given: a journal with active frames and history.
    journal = TurnJournal(max_frames=2)
    journal.stamp({"idx": 1}, final=False)
    journal.stamp({"idx": 2}, final=True)
    journal.stamp({"idx": 3}, final=False)
    assert journal.stats()["dropped"] == 1

    # When: clearing the journal.
    journal.clear()

    # Then: seq and stats are completely reset.
    assert journal.first_seq is None
    assert journal.last_seq is None
    assert journal.turn_id == 0
    assert journal.stats() == {"frames": 0, "bytes": 0, "dropped": 0, "turns_started": 0}

    # And when: stamping a new frame after clear.
    f = journal.stamp({"idx": 100}, final=False)
    assert f["seq"] == 1
    assert f["turn_id"] == 1
    assert journal.stats()["turns_started"] == 1
