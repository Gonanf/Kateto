// BrowserPcmPlayer (MASK-5): decodes pcm_s16le chunks from the Kateto event bus
// and schedules them on the phone's WebAudio graph. Dependency-free and DOM-free
// at top level so it can be imported from Node in the tests.
//
// Run tests with: cd kateto/mask/web && node --test browser-pcm-player.test.mjs

export const MASK_PROTOCOL = 1;

export function decodePcmS16le(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const n = bin.length >> 1;
  const out = new Int16Array(n);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let i = 0; i < n; i++) out[i] = view.getInt16(i * 2, true);
  return out;
}

export function pcm16ToFloat32(int16) {
  const out = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) out[i] = int16[i] / 32768;
  return out;
}

export function resampleLinear(float32, fromRate, toRate) {
  if (fromRate === toRate || float32.length === 0) return float32.slice();
  const ratio = toRate / fromRate;
  const outLen = Math.max(1, Math.round(float32.length * ratio));
  const out = new Float32Array(outLen);
  const last = float32.length - 1;
  for (let i = 0; i < outLen; i++) {
    const src = i / ratio;
    const i0 = Math.floor(src);
    const i1 = Math.min(i0 + 1, last);
    const frac = src - i0;
    out[i] = float32[i0] + (float32[i1] - float32[i0]) * frac;
  }
  return out;
}

export class BrowserPcmPlayer {
  constructor({ audioContextFactory, onStateChange, onFrame, leadMs = 60, maxQueueMs = 5000 } = {}) {
    this._audioContextFactory = audioContextFactory || (() => new AudioContext());
    this._onStateChange = onStateChange || (() => {});
    this._onFrame = onFrame || (() => {});
    this._leadMs = leadMs;
    this._maxQueueMs = maxQueueMs;
    this._ctx = null;
    this._queue = [];
    this._sources = new Set();
    this._nextStart = 0;
    this._playbackMs = 0;
    this._closed = false;
    this._lastState = "idle";
  }

  get state() {
    if (this._closed) return "closed";
    if (this._ctx && this._ctx.state === "suspended") return "suspended";
    if (this._sources.size > 0 || this._queue.length > 0) return "playing";
    return "idle";
  }

  get queuedMs() {
    let total = 0;
    for (const entry of this._queue) total += entry.durationMs;
    return total;
  }

  handleMessage(msg) {
    if (!msg || typeof msg !== "object") return "ignored";
    if (msg.event === "audio_output" && msg.type === "audio") return this.enqueueFrame(msg);
    if (msg.event === "interrupt") {
      this.interrupt(msg.reason);
      return "stopped";
    }
    return "ignored";
  }

  enqueueFrame(frame) {
    if (this._closed) return "ignored";
    if (!frame.audio_b64 && !frame.final) return "ignored";

    const ctx = this._ensureContext();
    const rate = ctx.sampleRate || frame.sample_rate || 24000;

    let samples;
    if (frame.audio_b64) {
      const floats = pcm16ToFloat32(decodePcmS16le(frame.audio_b64));
      samples =
        frame.sample_rate && frame.sample_rate !== rate
          ? resampleLinear(floats, frame.sample_rate, rate)
          : floats;
    } else {
      samples = new Float32Array(0);
    }

    const durationMs = (samples.length / rate) * 1000;
    this._queue.push({
      samples,
      final: !!frame.final,
      rms: typeof frame.rms === "number" ? frame.rms : 0,
      text: frame.text ?? null,
      seq: frame.seq ?? 0,
      voiceId: frame.voice_id ?? null,
      durationMs,
    });
    this._enforceQueueLimit();
    this._schedule();
    this._syncState();
    return "queued";
  }

  interrupt(reason) {
    for (const rec of this._sources) {
      try {
        rec.source.stop();
      } catch (_e) {
        /* already stopped */
      }
    }
    this._sources.clear();
    this._queue = [];
    this._playbackMs = 0;
    this._nextStart = 0;
    this._syncState();
  }

  unlock() {
    if (this._closed) return;
    const ctx = this._ensureContext();
    if (ctx.state === "suspended") {
      const maybe = ctx.resume();
      if (maybe && typeof maybe.then === "function") {
        maybe.then(() => {
          this._schedule();
          this._syncState();
        });
        return;
      }
    }
    this._schedule();
    this._syncState();
  }

  playbackMs() {
    return this._playbackMs;
  }

  close() {
    if (this._closed) return;
    this._closed = true;
    this._queue = [];
    for (const rec of this._sources) {
      try {
        rec.source.stop();
      } catch (_e) {
        /* already stopped */
      }
    }
    this._sources.clear();
    if (this._ctx && typeof this._ctx.close === "function") {
      try {
        this._ctx.close();
      } catch (_e) {
        /* already closed */
      }
    }
    this._syncState();
  }

  _ensureContext() {
    if (!this._ctx) this._ctx = this._audioContextFactory();
    return this._ctx;
  }

  _enforceQueueLimit() {
    while (this._queue.length > 0 && this.queuedMs > this._maxQueueMs) {
      this._queue.shift();
    }
  }

  _schedule() {
    const ctx = this._ctx;
    if (!ctx || ctx.state !== "running") return;
    while (this._queue.length > 0) {
      this._scheduleEntry(ctx, this._queue.shift());
    }
  }

  _scheduleEntry(ctx, entry) {
    const rate = ctx.sampleRate;
    const n = entry.samples.length;
    const durationSec = n / rate;
    const durationMs = durationSec * 1000;
    const startAt = Math.max(ctx.currentTime + this._leadMs / 1000, this._nextStart);
    this._nextStart = startAt + durationSec;

    const buffer = ctx.createBuffer(1, Math.max(1, n), rate);
    buffer.copyToChannel(entry.samples, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const rec = { source, final: entry.final };
    this._sources.add(rec);
    source.onended = () => this._onEnded(rec);
    source.start(startAt);

    const playbackStartMs = this._playbackMs;
    this._playbackMs += durationMs;
    this._onFrame({
      voiceId: entry.voiceId,
      rms: entry.rms,
      seq: entry.seq,
      playbackStartMs,
      durationMs,
      text: entry.text,
    });
  }

  _onEnded(rec) {
    this._sources.delete(rec);
    this._syncState();
  }

  _notifyState(state) {
    if (state === this._lastState) return;
    this._lastState = state;
    this._onStateChange(state);
  }

  _syncState() {
    this._notifyState(this.state);
  }
}
