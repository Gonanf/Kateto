export const RESUME_TYPE = 'mask_resume';
export const RESUME_EVENT = 'audio_resume';

export function createTurnDurability() {
  let lastSeq = 0;
  let turnId = 0;
  let turns = 0;
  let turnsSurvived = 0;
  let disconnects = 0;
  let resumes = 0;
  let duplicates = 0;
  let gaps = 0;
  let droppedThisTurn = false;

  function onFrame(frame) {
    if (!frame || typeof frame.seq !== 'number' || !Number.isFinite(frame.seq)) {
      if (frame && frame.turn_id != null) {
        turnId = frame.turn_id;
      }
      if (frame && frame.final) {
        turns++;
        turnsSurvived++;
        droppedThisTurn = false;
      }
      return { play: true, reason: 'unsequenced' };
    }

    const seq = frame.seq;
    if (frame.turn_id != null) {
      turnId = frame.turn_id;
    }

    if (seq <= lastSeq) {
      duplicates++;
      return { play: false, reason: 'duplicate' };
    }

    let reason = 'ok';
    if (seq > lastSeq + 1 && lastSeq > 0) {
      gaps++;
      reason = 'gap';
    }

    lastSeq = seq;

    if (frame.final) {
      turns++;
      turnsSurvived++;
      droppedThisTurn = false;
    }

    return { play: true, reason };
  }

  function onClose() {
    disconnects++;
    droppedThisTurn = true;
  }

  function onOpen() {
    if (lastSeq === 0) {
      return null;
    }
    resumes++;
    return {
      type: RESUME_TYPE,
      after_seq: lastSeq,
    };
  }

  function acceptResume(msg) {
    const rawFrames = (msg && Array.isArray(msg.frames)) ? msg.frames : [];
    const gap = Boolean(msg && msg.gap);
    let skipped = 0;
    const frames = [];

    for (const f of rawFrames) {
      if (f && typeof f.seq === 'number' && f.seq <= lastSeq) {
        skipped++;
      } else {
        frames.push(f);
      }
    }

    return { frames, gap, skipped };
  }

  function onTurnLost() {
    turns++;
  }

  function metrics() {
    const survived_pct = turns ? Math.round((1000 * turnsSurvived) / turns) / 10 : 0;
    return {
      turns,
      turnsSurvived,
      disconnects,
      resumes,
      duplicates,
      gaps,
      survived_pct,
    };
  }

  return {
    onFrame,
    onClose,
    onOpen,
    acceptResume,
    onTurnLost,
    metrics,
    get lastSeq() {
      return lastSeq;
    },
    get turnId() {
      return turnId;
    },
  };
}
