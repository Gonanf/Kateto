/**
 * Kateto Avatar & Subtitle Web Components
 * Unified visual overlay system for OBS overlay and Courtroom debate.
 *
 * Provides:
 * 1. computeJawKinematics(rms): pure physics kinematics for Muppet cutout jaw.
 * 2. chunkTextIntoSubtitles(text, maxWords): automatic subtitle phrase chunker.
 * 3. <kateto-avatar>: Reusable Web Component rendering head + jaw cutout layers with fallback.
 * 4. <kateto-subtitles>: Reusable automatically chunked subtitle component at 100 WPM.
 * 5. SubtitleStreamer: Paced subtitle delivery with synchronized jaw pulses and TTS.
 */

// 1. Pure jaw kinematics formula (Kateto visual overlay standard)
// Backend is authoritative (RMSProcessor + map_rms_to_jaw_transform -> 16px/4.5deg, floor 0.05).
// This function is kept as deterministic fallback for synthetic TTS (pulseWord) and
// when backend payload is absent. It is intentionally conservative (18px / 6deg)
// and deterministic (no Math.random per-frame jitter). For live audio, prefer
// setJawTransform({jawOffsetX, jawOffsetY, jawRotation, headOffsetY}) with backend values.
export function computeJawKinematics(rms) {
  if (typeof rms !== 'number' || rms < 0.015) {
    return { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0, headOffsetY: 0 };
  }
  const factor = Math.min(1.0, Math.max(0.0, Math.pow((rms - 0.015) / 0.985, 0.68)));
  const upMovement = -Number((factor * 18.0).toFixed(2));
  const tilt = Number((factor * 6.0).toFixed(2));
  const headBob = Number((-factor * 1.5).toFixed(2));

  return {
    jawOffsetX: 0,
    jawOffsetY: upMovement,
    jawRotation: tilt,
    headOffsetY: headBob,
  };
}

// Backend-authoritative kinematics (deterministic, no jitter).
// rms expected already normalized 0..1 (RMSProcessor output).
export function computeBackendKinematics(rms) {
  if (typeof rms !== 'number' || rms < 0.05) {
    return { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0, headOffsetY: 0 };
  }
  const factor = Math.min(1.0, Math.max(0.0, (rms - 0.05) / 0.95));
  const jawOffsetY = Number((factor * 16.0).toFixed(2));
  const jawRotation = Number((factor * 4.5).toFixed(2));
  const headOffsetY = Number((-factor * 1.8).toFixed(2));
  return { jawOffsetX: 0, jawOffsetY, jawRotation, headOffsetY };
}

// 2. Automatic Subtitle Chunker
// Breaks full turns into natural, easily readable subtitle phrases (~6-12 words max).
export function chunkTextIntoSubtitles(text, maxWords = 10) {
  if (!text) return [];
  const clean = text.trim();
  if (!clean) return [];

  // Match sentences first
  const sentences = clean.match(/[^.!?\n]+[.!?\n]*/g) || [clean];
  const chunks = [];

  for (let s of sentences) {
    s = s.trim();
    if (!s) continue;
    const words = s.split(/\s+/).filter(Boolean);
    if (words.length <= maxWords) {
      chunks.push(s);
    } else {
      let cur = [];
      for (let i = 0; i < words.length; i++) {
        cur.push(words[i]);
        const hasClauseBreak = /[,;:]$/.test(words[i]);
        if (cur.length >= maxWords || (hasClauseBreak && cur.length >= 6)) {
          chunks.push(cur.join(' '));
          cur = [];
        }
      }
      if (cur.length > 0) {
        chunks.push(cur.join(' '));
      }
    }
  }

  return chunks.length > 0 ? chunks : [clean];
}

// Voice display metadata
export const VOICE_NAMES = {
  jane: "Jane",
  doktor: "Doktor",
  conquest: "Conquest",
  whisperer: "Whisperer",
};

export const ROLE_LABELS = {
  orchestrator: "Judge",
  adversary: "Adversaria",
  project_manager: "Project Manager",
  agile_facilitator: "Agile Lead",
  delivery_advisor: "Delivery",
};

export function formatSpeakerName(voice_id, role) {
  if (!voice_id) return "Kateto";
  const key = voice_id.toLowerCase();
  const vName = VOICE_NAMES[key] || (voice_id.charAt(0).toUpperCase() + voice_id.slice(1));
  const rName = ROLE_LABELS[role] || role;
  return rName ? `${vName} (${rName})` : vName;
}

// Web Speech API Voice Selection & Garbage Collection Protection
let activeUtterance = null;
let cachedVoices = [];

function loadVoices() {
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    cachedVoices = window.speechSynthesis.getVoices();
  }
}
if (typeof window !== 'undefined' && window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = loadVoices;
  loadVoices();
}

function getBestVoice() {
  loadVoices();
  if (!cachedVoices.length) return null;
  const esVoice = cachedVoices.find(v => v.lang && v.lang.toLowerCase().startsWith('es'));
  if (esVoice) return esVoice;
  return cachedVoices[0];
}

// 3. Web Component: <kateto-avatar>
export class KatetoAvatar extends HTMLElement {
  static get observedAttributes() {
    return ['voice', 'idle', 'scale'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._voice = this.getAttribute('voice') || 'jane';
    this._useFallback = false;
    this._currentAnim = null;
    this._rms = 0;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: inline-block;
          position: relative;
          width: 100%;
          height: 100%;
          filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.55));
          overflow: visible;
        }
        .container {
          position: relative;
          width: 100%;
          height: 100%;
          overflow: visible;
        }
        .layer-head {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          object-fit: contain;
          z-index: 2;
          pointer-events: none;
          transform-origin: 50% 50%;
          will-change: transform;
          transition: transform 0.05s ease-out;
        }
        .layer-jaw {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          object-fit: contain;
          z-index: 1;
          transform-origin: 50% 22%;
          will-change: transform;
          transition: transform 0.04s ease-out;
          pointer-events: none;
        }
        .avatar-fallback {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          object-fit: contain;
          z-index: 2;
          display: none;
        }
      </style>
      <div class="container">
        <img id="head" class="layer-head" alt="Head" />
        <img id="jaw" class="layer-jaw" alt="Jaw" />
        <img id="fallback" class="avatar-fallback" alt="Classic" />
      </div>
    `;

    this._head = this.shadowRoot.getElementById('head');
    this._jaw = this.shadowRoot.getElementById('jaw');
    this._fallback = this.shadowRoot.getElementById('fallback');

    this._head.onerror = () => this._enableFallback();
    this._jaw.onerror = () => this._enableFallback();
    this._fallback.onerror = () => { this._fallback.style.display = 'none'; };
  }

  connectedCallback() {
    this._updateSources();
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue === newValue) return;
    if (name === 'voice') {
      this._voice = newValue || 'jane';
      this._useFallback = false;
      this._updateSources();
    }
  }

  get voice() {
    return this._voice;
  }

  set voice(val) {
    this.setAttribute('voice', val);
  }

  setVoice(voiceId) {
    this.voice = voiceId;
  }

  _enableFallback() {
    if (!this._useFallback) {
      this._useFallback = true;
      this._head.style.display = 'none';
      this._jaw.style.display = 'none';
      this._fallback.style.display = 'block';
      this._fallback.src = `/voices/${encodeURIComponent(this._voice)}/top.png`;
    }
  }

  _updateSources() {
    if (!this._voice) return;
    this._useFallback = false;
    this._head.style.display = 'block';
    this._jaw.style.display = 'block';
    this._fallback.style.display = 'none';
    this._jaw.style.transform = 'translate(0px, 0px) rotate(0deg)';
    this._head.style.transform = 'translateY(0px)';

    this._head.src = `/voices/${encodeURIComponent(this._voice)}/avatar_head.png`;
    this._jaw.src = `/voices/${encodeURIComponent(this._voice)}/avatar_jaw.png`;
    this._fallback.src = `/voices/${encodeURIComponent(this._voice)}/top.png`;
  }

  // Backend-authoritative transform: jaw moves with RMS, head has subtle opposite bob.
  setJawTransform({ jawOffsetX = 0, jawOffsetY = 0, jawRotation = 0, headOffsetY = 0 } = {}) {
    if (this._useFallback) {
      const active = (Math.abs(jawOffsetY) > 0.5 || Math.abs(jawRotation) > 0.3);
      this._fallback.src = active
        ? `/voices/${encodeURIComponent(this._voice)}/mouth.png`
        : `/voices/${encodeURIComponent(this._voice)}/top.png`;
      return;
    }
    this._jaw.style.transform = `translate(${jawOffsetX}px, ${jawOffsetY}px) rotate(${jawRotation}deg)`;
    if (headOffsetY !== 0 || this._head.style.transform !== 'translateY(0px)') {
      this._head.style.transform = `translateY(${headOffsetY}px)`;
    }
  }

  setRms(rms) {
    this._rms = rms;
    if (rms == null || typeof rms !== 'number') {
      this.setJawTransform({ jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0, headOffsetY: 0 });
      return;
    }
    // If backend provided explicit transform via setJawTransform, this is fallback path only.
    const { jawOffsetX, jawOffsetY, jawRotation, headOffsetY } = computeJawKinematics(rms);
    this.setJawTransform({ jawOffsetX, jawOffsetY, jawRotation, headOffsetY });
  }

  pulseWord(wordDurationMs = 385) {
    if (this._currentAnim) {
      cancelAnimationFrame(this._currentAnim);
      this._currentAnim = null;
    }

    const start = performance.now();
    const peakAmp = 0.16 + (Math.random() * 0.28);
    const self = this;

    function step(now) {
      const elapsed = now - start;
      if (elapsed >= wordDurationMs) {
        self.setRms(0);
        self._currentAnim = null;
        return;
      }

      const progress = elapsed / wordDurationMs;
      let curve = 0;
      if (progress < 0.35) {
        curve = Math.sin((progress / 0.35) * (Math.PI / 2));
      } else if (progress < 0.85) {
        curve = Math.cos(((progress - 0.35) / 0.50) * (Math.PI / 2));
      } else {
        curve = 0;
      }

      const activeRms = peakAmp * curve;
      self.setRms(activeRms);

      self._currentAnim = requestAnimationFrame(step);
    }

    this._currentAnim = requestAnimationFrame(step);
  }

  stopSpeaking() {
    if (this._currentAnim) {
      cancelAnimationFrame(this._currentAnim);
      this._currentAnim = null;
    }
    this.setRms(0);
  }
}

if (!customElements.get('kateto-avatar')) {
  customElements.define('kateto-avatar', KatetoAvatar);
}

// 4. SubtitleStreamer: Calibrated to match TTS speech cadence (~155 WPM, 385ms/word)
export class SubtitleStreamer {
  constructor(options = {}) {
    this.wpm = options.wpm || 190;
    this.msPerWord = Math.round(60000 / this.wpm); // ~315ms
    this.enableTts = options.enableTts !== undefined ? options.enableTts : false;
    this.hasBackendAudio = false;
    this.queue = [];
    this.isPlaying = false;
    this._currentTimer = null;
    this.onStartTurn = options.onStartTurn || null;
    this.onStartChunk = options.onStartChunk || null;
    this.onWord = options.onWord || null;
    this.onEndChunk = options.onEndChunk || null;
    this.onEndTurn = options.onEndTurn || null;
    this.currentTurn = null;
    this.lastFinishedText = "";
  }

  enqueue(item) {
    if (!item || !item.text) return;
    const clean = item.text.trim();
    if (!clean) return;

    // Prevent duplicate delivery: reject if currently speaking, just finished, or already in queue
    if (this.currentTurn && this.currentTurn.text && this.currentTurn.text.trim() === clean) {
      return;
    }
    if (this.lastFinishedText === clean) {
      return;
    }
    if (this.queue.some(q => q.text && q.text.trim() === clean)) {
      return;
    }

    this.queue.push(item);
    if (!this.isPlaying) {
      this._playNextTurn();
    }
  }

  clear() {
    if (this._currentTimer) {
      clearTimeout(this._currentTimer);
      this._currentTimer = null;
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    this.queue = [];
    this.currentTurn = null;
    this.isPlaying = false;
  }

  _speakChunk(text) {
    if (!this.enableTts || this.hasBackendAudio || typeof window === 'undefined' || !window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      window.speechSynthesis.resume();
      const utter = new SpeechSynthesisUtterance(text);
      activeUtterance = utter;
      const voice = getBestVoice();
      if (voice) utter.voice = voice;
      utter.rate = 1.0;
      utter.onend = () => { if (activeUtterance === utter) activeUtterance = null; };
      utter.onerror = () => { if (activeUtterance === utter) activeUtterance = null; };
      setTimeout(() => {
        try {
          window.speechSynthesis.resume();
          window.speechSynthesis.speak(utter);
        } catch (e) {}
      }, 30);
    } catch (e) {
      console.warn('TTS error:', e);
    }
  }

  _playNextTurn() {
    if (this.queue.length === 0) {
      this.isPlaying = false;
      this.currentTurn = null;
      return;
    }

    this.isPlaying = true;
    const turn = this.queue.shift();
    this.currentTurn = turn;
    const chunks = chunkTextIntoSubtitles(turn.text, 10);

    if (chunks.length === 0) {
      this.lastFinishedText = turn.text ? turn.text.trim() : "";
      this.currentTurn = null;
      if (this.onEndTurn) this.onEndTurn(turn);
      if (turn.onEnd) turn.onEnd();
      this._playNextTurn();
      return;
    }

    if (this.onStartTurn) this.onStartTurn(turn);
    if (turn.onStart) turn.onStart(turn);

    let chunkIndex = 0;

    const playChunk = () => {
      if (chunkIndex >= chunks.length) {
        this.lastFinishedText = turn.text ? turn.text.trim() : "";
        this.currentTurn = null;
        if (this.onEndTurn) this.onEndTurn(turn);
        if (turn.onEnd) turn.onEnd();
        const turnPause = this.queue.length > 0 ? 120 : 350;
        this._currentTimer = setTimeout(() => {
          this._playNextTurn();
        }, turnPause);
        return;
      }

      const chunkText = chunks[chunkIndex];
      const rawWords = chunkText.split(/\s+/).filter(Boolean);

      if (this.onStartChunk) {
        this.onStartChunk(chunkText, chunkIndex + 1, chunks.length, turn);
      }
      if (turn.onStartChunk) {
        turn.onStartChunk(chunkText, chunkIndex + 1, chunks.length);
      }

      this._speakChunk(chunkText);

      let wordIndex = 0;
      let accumulated = '';

      const emitWord = () => {
        if (wordIndex < rawWords.length) {
          const word = rawWords[wordIndex];
          accumulated += (wordIndex > 0 ? ' ' : '') + word;
          const isLast = (wordIndex === rawWords.length - 1);

          let delay = this.msPerWord;
          if (this.queue.length > 0) {
            delay = Math.round(delay * 0.75); // Catch up if waiting in queue
          }
          if (/[.!?]$/.test(word)) delay += 80;
          else if (/[,;:]$/.test(word)) delay += 40;

          if (this.onWord) {
            this.onWord({ word, accumulated, wordIndex, totalWords: rawWords.length, isLast, delay, turn });
          }
          if (turn.onWord) {
            turn.onWord({ word, accumulated, wordIndex, totalWords: rawWords.length, isLast, delay });
          }

          wordIndex++;
          this._currentTimer = setTimeout(emitWord, delay);
        } else {
          if (this.onEndChunk) this.onEndChunk(chunkText, turn);
          if (turn.onEndChunk) turn.onEndChunk(chunkText);

          chunkIndex++;
          // Snappy transition between phrases so UI stays in lockstep with TTS audio
          const chunkPause = this.queue.length > 0 ? 80 : 250;
          this._currentTimer = setTimeout(playChunk, chunkPause);
        }
      };

      emitWord();
    };

    playChunk();
  }
}

// 5. Web Component: <kateto-subtitles>
// Unified automatically chunked subtitle component for Visual Overlay and Courtroom.
export class KatetoSubtitles extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._currentAvatar = null;
    this._idleTimer = null;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          max-width: 900px;
          margin: 0 auto;
          box-sizing: border-box;
          user-select: none;
        }
        .box {
          background: rgba(18, 14, 12, 0.90);
          border: 2px solid #d9b36b;
          border-radius: 10px;
          box-shadow: 0 0 0 1px rgba(0,0,0,0.5), 0 8px 30px rgba(0,0,0,0.8);
          backdrop-filter: blur(8px);
          padding: 14px 22px 18px;
          color: #ffffff;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          transition: opacity 0.3s ease, transform 0.3s ease;
        }
        .box.idle {
          opacity: 0.92;
        }
        .header-row {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 8px;
        }
        .who {
          font-weight: 700;
          font-size: 1.05rem;
          letter-spacing: 0.05em;
          color: #d9b36b;
          text-transform: uppercase;
          background: rgba(217, 179, 107, 0.15);
          border: 1px solid rgba(217, 179, 107, 0.4);
          border-radius: 4px;
          padding: 2px 10px;
        }
        .who.judge {
          color: #ff6b6b;
          background: rgba(255, 107, 107, 0.15);
          border-color: rgba(255, 107, 107, 0.4);
        }
        .phase-tag {
          font-size: 0.7rem;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          background: #3a2415;
          color: #f3e7c9;
          padding: 2px 8px;
          border-radius: 4px;
          border: 1px solid #d9b36b;
        }
        .chunk-counter {
          margin-left: auto;
          font-size: 0.75rem;
          letter-spacing: 0.08em;
          color: rgba(217, 179, 107, 0.8);
          font-family: monospace;
        }
        .dialogue-text {
          font-size: 1.22rem;
          line-height: 1.45;
          min-height: 2.5em;
          color: #ffffff;
          text-shadow: 0 1px 3px rgba(0,0,0,0.8);
          word-break: break-word;
        }
      </style>
      <div class="box" id="box">
        <div class="header-row">
          <span class="who" id="who">Kateto</span>
          <span class="phase-tag" id="phase">ready</span>
          <span class="chunk-counter" id="counter"></span>
        </div>
        <div class="dialogue-text" id="text">Waiting for debate&hellip;</div>
      </div>
    `;

    this._box = this.shadowRoot.getElementById('box');
    this._who = this.shadowRoot.getElementById('who');
    this._phase = this.shadowRoot.getElementById('phase');
    this._counter = this.shadowRoot.getElementById('counter');
    this._text = this.shadowRoot.getElementById('text');

    this.streamer = new SubtitleStreamer({
      wpm: 190,
      enableTts: false,
      onStartTurn: (turn) => {
        if (this._idleTimer) clearTimeout(this._idleTimer);
        const label = formatSpeakerName(turn.voice_id, turn.role);
        this._who.textContent = label;
        this._who.className = "who" + (turn.role === "orchestrator" ? " judge" : "");
        this._phase.textContent = (turn.phase || "speaking").toUpperCase();
        this._text.textContent = "";
        this._box.classList.remove('idle');
        this.dispatchEvent(new CustomEvent('turnstart', { detail: turn, bubbles: true, composed: true }));
      },
      onStartChunk: (chunkText, curChunk, totalChunks, turn) => {
        this._counter.textContent = totalChunks > 1 ? `${curChunk}/${totalChunks}` : '';
        this._text.textContent = '';
      },
      onWord: ({ accumulated, delay, turn }) => {
        this._text.textContent = accumulated;
        if (turn.avatar && typeof turn.avatar.pulseWord === 'function') {
          turn.avatar.pulseWord(delay);
        }
      },
      onEndChunk: (chunkText, turn) => {
        if (turn.avatar && typeof turn.avatar.stopSpeaking === 'function') {
          turn.avatar.stopSpeaking();
        }
      },
      onEndTurn: (turn) => {
        if (turn.avatar && typeof turn.avatar.stopSpeaking === 'function') {
          turn.avatar.stopSpeaking();
        }
        this.dispatchEvent(new CustomEvent('turnend', { detail: turn, bubbles: true, composed: true }));
        this._idleTimer = setTimeout(() => {
          this._box.classList.add('idle');
        }, 3000);
      }
    });
  }

  setBackendAudio(active) {
    this.streamer.hasBackendAudio = !!active;
    if (active && typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  }

  setTts(enable) {
    this.streamer.enableTts = enable;
  }

  get ttsEnabled() {
    return this.streamer.enableTts;
  }

  displayTurn({ voice_id, role, phase, text, avatar }) {
    this.streamer.enqueue({ voice_id, role, phase, text, avatar });
  }

  restoreState({ voice_id, role, phase, text }) {
    if (!voice_id && !text) return;
    const label = formatSpeakerName(voice_id, role);
    this._who.textContent = label;
    this._who.className = "who" + (role === "orchestrator" ? " judge" : "");
    this._phase.textContent = (phase || "speaking").toUpperCase();
    this._counter.textContent = "";
    this._text.textContent = text || "";
    this._box.classList.remove('idle');
  }

  clear() {
    this.streamer.clear();
    this._text.textContent = "";
    this._counter.textContent = "";
  }
}

if (!customElements.get('kateto-subtitles')) {
  customElements.define('kateto-subtitles', KatetoSubtitles);
}

// 6. Live Web Audio PCM Stream Player for Browser Overlays
export class BrowserPcmPlayer {
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || 24000;
    this.ctx = null;
    this.nextTime = 0;
    this.enabled = options.enabled !== undefined ? options.enabled : false;
  }

  enable() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx({ sampleRate: this.sampleRate });
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
    this.enabled = true;
  }

  disable() {
    this.enabled = false;
    this.stop();
  }

  stop() {
    if (this.ctx) {
      try { this.ctx.close(); } catch (e) {}
      this.ctx = null;
      this.nextTime = 0;
    }
  }

  playChunk(base64Data, sampleRate, channels = 1) {
    if (!this.enabled || !base64Data) return;
    try {
      if (!this.ctx) this.enable();
      if (this.ctx.state === 'suspended') {
        this.ctx.resume();
      }

      const binary = atob(base64Data);
      const len = binary.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
      const int16 = new Int16Array(bytes.buffer);
      const float32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0;
      }

      const rate = sampleRate || this.sampleRate;
      const audioBuffer = this.ctx.createBuffer(channels, float32.length, rate);
      audioBuffer.copyToChannel(float32, 0);

      const source = this.ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.ctx.destination);

      const now = this.ctx.currentTime;
      if (this.nextTime < now) {
        this.nextTime = now + 0.02;
      }
      source.start(this.nextTime);
      this.nextTime += audioBuffer.duration;
    } catch (e) {
      console.warn("BrowserPcmPlayer playback error:", e);
    }
  }
}

