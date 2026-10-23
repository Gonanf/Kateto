import test from 'node:test';
import assert from 'node:assert/strict';

import { createTurnDurability, RESUME_TYPE, RESUME_EVENT } from './mask-durability.js';

test('primer frame: play true, lastSeq actualizado', () => {
  const d = createTurnDurability();
  const res = d.onFrame({ seq: 1, turn_id: 1, audio: 'data' });
  assert.equal(res.play, true);
  assert.equal(res.reason, 'ok');
  assert.equal(d.lastSeq, 1);
  assert.equal(d.turnId, 1);
});

test('frame con seq ya visto no se reproduce', () => {
  const d = createTurnDurability();
  d.onFrame({ seq: 1, turn_id: 1 });
  d.onFrame({ seq: 2, turn_id: 1 });
  const res = d.onFrame({ seq: 2, turn_id: 1 });
  assert.equal(res.play, false);
  assert.equal(res.reason, 'duplicate');
  assert.equal(d.lastSeq, 2);
  assert.equal(d.metrics().duplicates, 1);
});

test('salto de seq se reporta como gap y se reproduce igual', () => {
  const d = createTurnDurability();
  d.onFrame({ seq: 1, turn_id: 1 });
  const res = d.onFrame({ seq: 4, turn_id: 1 });
  assert.equal(res.play, true);
  assert.equal(res.reason, 'gap');
  assert.equal(d.lastSeq, 4);
  assert.equal(d.metrics().gaps, 1);
});

test('frame sin seq se reproduce sin dedupear', () => {
  const d = createTurnDurability();
  const res1 = d.onFrame({ audio: 'abc' });
  const res2 = d.onFrame({ audio: 'abc' });
  assert.equal(res1.play, true);
  assert.equal(res1.reason, 'unsequenced');
  assert.equal(res2.play, true);
  assert.equal(res2.reason, 'unsequenced');
  assert.equal(d.lastSeq, 0);
});

test('onOpen sin frames previos devuelve null', () => {
  const d = createTurnDurability();
  assert.equal(d.onOpen(), null);
  assert.equal(d.metrics().resumes, 0);
});

test('onOpen tras una caida pide mask_resume con after_seq del ultimo frame', () => {
  const d = createTurnDurability();
  d.onFrame({ seq: 7, turn_id: 2 });
  d.onClose();
  const req = d.onOpen();
  assert.deepEqual(req, {
    type: RESUME_TYPE,
    after_seq: 7,
  });
  assert.equal(d.metrics().resumes, 1);
  assert.equal(d.metrics().disconnects, 1);
});

test('acceptResume filtra lo ya reproducido y cuenta skipped', () => {
  const d = createTurnDurability();
  d.onFrame({ seq: 3, turn_id: 1 });
  const msg = {
    event: RESUME_EVENT,
    type: 'resume',
    after_seq: 1,
    gap: false,
    frames: [
      { seq: 2, turn_id: 1 },
      { seq: 3, turn_id: 1 },
      { seq: 4, turn_id: 1 },
      { seq: 5, turn_id: 1 },
    ],
  };
  const res = d.acceptResume(msg);
  assert.equal(res.skipped, 2);
  assert.equal(res.gap, false);
  assert.deepEqual(res.frames, [
    { seq: 4, turn_id: 1 },
    { seq: 5, turn_id: 1 },
  ]);
});

test('onClose solo cuenta la caida: no corta el audio', () => {
  const d = createTurnDurability();
  d.onFrame({ seq: 1, turn_id: 1 });
  d.onClose();
  const m = d.metrics();
  assert.equal(m.disconnects, 1);
  assert.equal(d.lastSeq, 1);
});

test('metricas: turnos sobrevividos y pct', () => {
  const d = createTurnDurability();
  // Turno 1 con final: sobrevive
  d.onFrame({ seq: 1, turn_id: 1 });
  d.onFrame({ seq: 2, turn_id: 1, final: true });

  // Turno 2 con caída y reanudación, con final: sobrevive
  d.onFrame({ seq: 3, turn_id: 2 });
  d.onClose();
  d.onOpen();
  d.onFrame({ seq: 4, turn_id: 2, final: true });

  const m = d.metrics();
  assert.equal(m.turns, 2);
  assert.equal(m.turnsSurvived, 2);
  assert.equal(m.disconnects, 1);
  assert.equal(m.resumes, 1);
  assert.equal(m.survived_pct, 100.0);
});

test('onTurnLost cuenta el turno sin sobrevivir', () => {
  const d = createTurnDurability();
  d.onFrame({ seq: 1, turn_id: 1, final: true });
  d.onTurnLost();

  const m = d.metrics();
  assert.equal(m.turns, 2);
  assert.equal(m.turnsSurvived, 1);
  assert.equal(m.survived_pct, 50.0);
});
