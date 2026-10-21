// Tests de BrowserPcmPlayer (MASK-5).
// Corre con: cd kateto/mask/web && node --test browser-pcm-player.test.mjs

import { describe, it } from "node:test";
import assert from "node:assert/strict";

const mod = await import("./browser-pcm-player.js");
const {
  MASK_PROTOCOL,
  decodePcmS16le,
  pcm16ToFloat32,
  resampleLinear,
  BrowserPcmPlayer,
} = mod;

// --- Fakes de WebAudio (sin DOM) ---

class FakeBuffer {
  constructor(channels, length, sampleRate) {
    this.numberOfChannels = channels;
    this.length = length;
    this.sampleRate = sampleRate;
    this._channels = Array.from({ length: channels }, () => new Float32Array(length));
  }
  copyToChannel(source, channel) {
    this._channels[channel].set(source);
  }
}

class FakeBufferSource {
  constructor(ctx) {
    this.ctx = ctx;
    this.buffer = null;
    this.onended = null;
    this.startCalls = [];
    this.stopCalls = 0;
    this._ended = false;
  }
  connect(dest) {
    this.destination = dest;
  }
  start(when) {
    this.startCalls.push(when);
  }
  stop() {
    this.stopCalls += 1;
    this.fireEnded();
  }
  fireEnded() {
    if (this._ended) return;
    this._ended = true;
    if (typeof this.onended === "function") this.onended();
  }
}

class FakeAudioContext {
  constructor({ state = "running" } = {}) {
    this.sampleRate = 48000;
    this.currentTime = 0;
    this.state = state;
    this.destination = {};
    this._sources = [];
    this.resumeCalls = 0;
    this.closed = false;
  }
  createBuffer(channels, length, sampleRate) {
    return new FakeBuffer(channels, length, sampleRate);
  }
  createBufferSource() {
    const source = new FakeBufferSource(this);
    this._sources.push(source);
    return source;
  }
  resume() {
    this.resumeCalls += 1;
    this.state = "running";
  }
  close() {
    this.closed = true;
    this.state = "closed";
  }
}

function makeCtx(state = "running") {
  const ctx = new FakeAudioContext({ state });
  return { ctx, factory: () => ctx };
}

function int16Of(ms, rate = 48000, amp = 0.5) {
  const n = Math.round((ms / 1000) * rate);
  const out = new Int16Array(n);
  out.fill(Math.round(amp * 32767));
  return out;
}

function frameOf(samples, opts = {}) {
  const bytes = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
  return {
    event: "audio_output",
    type: "audio",
    protocol: MASK_PROTOCOL,
    voice_id: opts.voiceId ?? "jane",
    sample_rate: opts.sampleRate ?? 48000,
    channels: 1,
    format: "pcm_s16le",
    seq: opts.seq ?? 0,
    final: opts.final ?? false,
    audio_b64: Buffer.from(bytes).toString("base64"),
    rms: opts.rms ?? 0.4,
    text: opts.text ?? null,
  };
}

describe("decodePcmS16le", () => {
  it("decode pcm_s16le little-endian con signo", () => {
    const input = new Int16Array([-32768, 0, 32767]);
    const bytes = new Uint8Array(input.buffer);
    assert.deepEqual([...bytes], [0x00, 0x80, 0x00, 0x00, 0xff, 0x7f]);
    const b64 = Buffer.from(bytes).toString("base64");
    const decoded = decodePcmS16le(b64);
    assert.deepEqual([...decoded], [-32768, 0, 32767]);
  });
});

describe("pcm16ToFloat32", () => {
  it("pcm16ToFloat32 mapea a [-1,1)", () => {
    const out = pcm16ToFloat32(new Int16Array([-32768, 0, 32767]));
    assert.equal(out[0], -1);
    assert.equal(out[1], 0);
    assert.ok(Math.abs(out[2] - 32767 / 32768) < 1e-6);
    assert.ok(out[2] < 1);
  });
});

describe("resampleLinear", () => {
  it("resampleLinear conserva DC y cambia la longitud", () => {
    const n = 22050;
    const dc = 0.25;
    const input = new Float32Array(n).fill(dc);
    const out = resampleLinear(input, 22050, 48000);
    assert.equal(out.length, 48000);
    assert.ok(Math.abs(out.length / n - 48000 / 22050) < 1e-9);
    for (let i = 0; i < out.length; i++) {
      assert.ok(Math.abs(out[i] - dc) < 1e-6, `idx ${i}: ${out[i]}`);
    }
  });
});

describe("BrowserPcmPlayer", () => {
  it("enqueueFrame agenda fuentes en serie", () => {
    const { ctx, factory } = makeCtx();
    const player = new BrowserPcmPlayer({ audioContextFactory: factory });
    player.enqueueFrame(frameOf(int16Of(100)));
    player.enqueueFrame(frameOf(int16Of(100)));

    const [s1, s2] = ctx._sources;
    assert.equal(s1.startCalls.length, 1);
    assert.equal(s2.startCalls.length, 1);
    const start1 = s1.startCalls[0];
    const dur1 = (int16Of(100).length / 48000) * 1000;
    assert.ok(Math.abs(s2.startCalls[0] - (start1 + dur1 / 1000)) < 1e-6);
    assert.ok(Math.abs(player.playbackMs() - 200) < 1e-6);
  });

  it("handleMessage enruta audio, ready e interrupt", () => {
    const { factory } = makeCtx();
    const player = new BrowserPcmPlayer({ audioContextFactory: factory });
    assert.equal(player.handleMessage(frameOf(int16Of(20))), "queued");
    assert.equal(player.handleMessage({ event: "mask_ready", type: "ready", protocol: 1 }), "ignored");
    assert.equal(player.handleMessage({ event: "interrupt", reason: "voice_activity" }), "stopped");
  });

  it("interrupt corta las fuentes y vacía la cola", () => {
    const { ctx, factory } = makeCtx();
    const player = new BrowserPcmPlayer({ audioContextFactory: factory });
    player.enqueueFrame(frameOf(int16Of(100)));
    player.enqueueFrame(frameOf(int16Of(100)));
    assert.equal(ctx._sources.length, 2);

    player.interrupt("voice_activity");
    assert.equal(ctx._sources[0].stopCalls, 1);
    assert.equal(ctx._sources[1].stopCalls, 1);
    assert.equal(player.state, "idle");
    assert.equal(player.playbackMs(), 0);

    player.enqueueFrame(frameOf(int16Of(50)));
    const third = ctx._sources[2];
    assert.ok(Math.abs(third.startCalls[0] - (ctx.currentTime + 0.06)) < 1e-6);
  });

  it("frame final cierra el turno al terminar la última fuente", () => {
    const { ctx, factory } = makeCtx();
    const states = [];
    const player = new BrowserPcmPlayer({
      audioContextFactory: factory,
      onStateChange: (s) => states.push(s),
    });
    player.enqueueFrame(frameOf(int16Of(100), { final: true }));
    assert.equal(player.state, "playing");
    ctx._sources[0].fireEnded();
    assert.equal(player.state, "idle");
    assert.ok(states.includes("idle"));
  });

  it("contexto suspendido encola y unlock agenda", () => {
    const { ctx, factory } = makeCtx("suspended");
    const player = new BrowserPcmPlayer({ audioContextFactory: factory });
    player.enqueueFrame(frameOf(int16Of(100)));
    assert.equal(ctx._sources.length, 0);

    player.unlock();
    assert.equal(ctx.resumeCalls, 1);
    assert.equal(ctx._sources.length, 1);
    assert.equal(ctx._sources[0].startCalls.length, 1);
  });

  it("la cola respeta maxQueueMs", () => {
    const { ctx, factory } = makeCtx("suspended");
    const player = new BrowserPcmPlayer({ audioContextFactory: factory, maxQueueMs: 200 });
    player.enqueueFrame(frameOf(int16Of(100), { seq: 0 }));
    player.enqueueFrame(frameOf(int16Of(100), { seq: 1 }));
    player.enqueueFrame(frameOf(int16Of(100), { seq: 2 }));

    assert.equal(player.queuedMs, 200);
    assert.equal(ctx._sources.length, 0);
    assert.deepEqual(
      player._queue.map((e) => e.seq),
      [1, 2],
    );
  });

  it("onFrame reporta playbackStartMs y rms", () => {
    const { factory } = makeCtx();
    const seen = [];
    const player = new BrowserPcmPlayer({
      audioContextFactory: factory,
      onFrame: (info) => seen.push(info),
    });
    player.enqueueFrame(frameOf(int16Of(100), { rms: 0.7, seq: 1 }));
    player.enqueueFrame(frameOf(int16Of(100), { rms: 0.2, seq: 2 }));

    assert.equal(seen.length, 2);
    assert.equal(seen[0].rms, 0.7);
    assert.equal(seen[1].rms, 0.2);
    assert.ok(seen[1].playbackStartMs > seen[0].playbackStartMs);
    assert.ok(Math.abs(seen[1].playbackStartMs - 100) < 1e-6);
  });
});
