/**
 * KatetoPaperTranscript - Court Reporter Official Paper Transcript
 * 
 * Provides an authentic legal stenographer parchment transcript on the screen side,
 * typing debate arguments character-by-character with mechanical clicking sounds
 * (/sounds/clicking1.wav - clicking14.wav) and carriage return (/sounds/return.mp3).
 */

const CLICK_URLS = Array.from({ length: 14 }, (_, i) => `/sounds/clicking${i + 1}.wav`);
const RETURN_URL = '/sounds/return.mp3';

class SoundController {
  constructor() {
    this.enabled = true;
    this.ctx = null;
    this.clickBuffers = [];
    this.returnBuffer = null;
    this.isLoaded = false;
    this._initAudio();
  }

  async _initAudio() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      this.ctx = new AudioCtx();

      // Unlock audio on first user gesture
      const unlock = () => {
        if (this.ctx && this.ctx.state === 'suspended') {
          this.ctx.resume();
        }
        window.removeEventListener('click', unlock);
        window.removeEventListener('keydown', unlock);
      };
      window.addEventListener('click', unlock);
      window.addEventListener('keydown', unlock);

      // Load buffers in background
      const loadBuffer = async (url) => {
        try {
          const res = await fetch(url);
          const arrayBuffer = await res.arrayBuffer();
          return await this.ctx.decodeAudioData(arrayBuffer);
        } catch {
          return null;
        }
      };

      const clicks = await Promise.all(CLICK_URLS.map(loadBuffer));
      this.clickBuffers = clicks.filter(Boolean);
      this.returnBuffer = await loadBuffer(RETURN_URL);
      this.isLoaded = true;
    } catch {
      // Audio context not available or fetch blocked
    }
  }

  playClick() {
    if (!this.enabled || !this.ctx || this.clickBuffers.length === 0) return;
    try {
      if (this.ctx.state === 'suspended') this.ctx.resume();
      const idx = Math.floor(Math.random() * this.clickBuffers.length);
      const buf = this.clickBuffers[idx];
      if (!buf) return;

      const source = this.ctx.createBufferSource();
      source.buffer = buf;
      // Slight pitch variation for organic mechanical feel
      source.playbackRate.value = 0.94 + Math.random() * 0.12;

      const gain = this.ctx.createGain();
      // Subtle, quiet mechanical keystrokes that do not overpower speech
      gain.gain.value = 0.05 + Math.random() * 0.02;

      source.connect(gain);
      gain.connect(this.ctx.destination);
      source.start(0);
    } catch {}
  }

  playReturn() {
    if (!this.enabled || !this.ctx || !this.returnBuffer) return;
    try {
      if (this.ctx.state === 'suspended') this.ctx.resume();
      const source = this.ctx.createBufferSource();
      source.buffer = this.returnBuffer;
      const gain = this.ctx.createGain();
      gain.gain.value = 0.08; // Gentle carriage return
      source.connect(gain);
      gain.connect(this.ctx.destination);
      source.start(0);
    } catch {}
  }

  toggleSound() {
    this.enabled = !this.enabled;
    return this.enabled;
  }
}

export class KatetoPaperTranscript extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.sound = new SoundController();
    this.turnQueue = [];
    this.isTyping = false;
    this.collapsed = false;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          position: absolute;
          top: 20px;
          right: 20px;
          bottom: 120px;
          width: 380px;
          max-width: 32vw;
          z-index: 40;
          pointer-events: auto;
          font-family: 'Courier New', Courier, monospace;
        }

        .paper-container {
          position: relative;
          width: 100%;
          height: 100%;
          background: #fdfbf7;
          background-image: 
            radial-gradient(ellipse at 50% 0%, rgba(255,255,255,0.7) 0%, rgba(244,238,224,0.3) 100%),
            linear-gradient(90deg, rgba(231,76,60,0.2) 0px, transparent 1px, transparent 38px, rgba(231,76,60,0.3) 39px, transparent 40px);
          border: 1px solid #d4c5a9;
          border-radius: 4px;
          box-shadow: 0 12px 36px rgba(0,0,0,0.55), 0 2px 8px rgba(0,0,0,0.3);
          display: flex;
          flex-direction: column;
          overflow: hidden;
          transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
        }

        :host(.collapsed) .paper-container {
          transform: translateX(calc(100% - 44px));
          opacity: 0.85;
        }

        /* Top Clip / Header Bar */
        .paper-header {
          background: #2a1810;
          color: #d4af37;
          padding: 10px 14px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          border-bottom: 2px solid #b8860b;
          user-select: none;
          box-shadow: 0 2px 6px rgba(0,0,0,0.4);
        }

        .header-title {
          font-size: 0.78rem;
          letter-spacing: 0.15em;
          text-transform: uppercase;
          font-weight: bold;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .header-controls {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .btn-ctrl {
          background: rgba(255,255,255,0.1);
          border: 1px solid #8b6b23;
          color: #f4eee0;
          font-size: 0.72rem;
          padding: 3px 7px;
          border-radius: 3px;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .btn-ctrl:hover {
          background: rgba(212,175,55,0.25);
          color: #fff;
        }
        .btn-ctrl.muted {
          opacity: 0.55;
          text-decoration: line-through;
        }

        /* Paper Body Scroll Area */
        .paper-body {
          flex: 1;
          padding: 16px 14px 16px 48px; /* Offset for red legal margin */
          overflow-y: auto;
          overflow-x: hidden;
          scroll-behavior: smooth;
        }

        .paper-body::-webkit-scrollbar {
          width: 6px;
        }
        .paper-body::-webkit-scrollbar-thumb {
          background: #c2b193;
          border-radius: 3px;
        }

        .seal-watermark {
          text-align: center;
          font-size: 0.68rem;
          letter-spacing: 0.25em;
          text-transform: uppercase;
          color: #a89f91;
          margin-bottom: 14px;
          border-bottom: 1px dashed #dcd3c1;
          padding-bottom: 8px;
        }

        /* Entries on paper */
        .transcript-entry {
          margin-bottom: 14px;
          font-size: 0.84rem;
          line-height: 1.55;
          color: #222;
          word-break: break-word;
        }

        .entry-header {
          font-size: 0.74rem;
          font-weight: bold;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-bottom: 4px;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        /* Speaker ink colors */
        .entry-header.jane { color: #5b21b6; }
        .entry-header.whisperer { color: #065f46; }
        .entry-header.doktor { color: #1e40af; }
        .entry-header.conquest { color: #92400e; }

        .entry-text {
          white-space: pre-wrap;
        }

        .objection-banner {
          background: #fef2f2;
          border: 1px solid #f87171;
          color: #b91c1c;
          font-weight: bold;
          text-align: center;
          padding: 6px;
          margin: 10px 0;
          font-size: 0.76rem;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          border-radius: 3px;
          animation: flashRed 0.4s ease 2;
        }

        @keyframes flashRed {
          0%, 100% { background: #fef2f2; }
          50% { background: #fee2e2; transform: scale(1.02); }
        }

        .typewriter-cursor {
          display: inline-block;
          width: 7px;
          height: 14px;
          background: #111;
          vertical-align: middle;
          margin-left: 2px;
          animation: blink 0.7s infinite;
        }

        @keyframes blink {
          0%, 49% { opacity: 1; }
          50%, 100% { opacity: 0; }
        }
      </style>

      <div class="paper-container">
        <div class="paper-header">
          <div class="header-title">
            <span>📜</span> ACTA JUDICIAL
          </div>
          <div class="header-controls">
            <button class="btn-ctrl" id="btn-sound" title="Alternar sonido de máquina de escribir">🔊 SFX</button>
            <button class="btn-ctrl" id="btn-collapse" title="Minimizar / Expandir acta">↔</button>
          </div>
        </div>

        <div class="paper-body" id="paper-body">
          <div class="seal-watermark">
            TRIBUNAL DE KATETO • ACTA TAQUIGRÁFICA OFICIAL
          </div>
          <div id="entries-container"></div>
        </div>
      </div>
    `;

    this._container = this.shadowRoot.getElementById('entries-container');
    this._body = this.shadowRoot.getElementById('paper-body');
    this._btnSound = this.shadowRoot.getElementById('btn-sound');
    this._btnCollapse = this.shadowRoot.getElementById('btn-collapse');

    this._btnSound.addEventListener('click', () => {
      const active = this.sound.toggleSound();
      this._btnSound.classList.toggle('muted', !active);
      this._btnSound.textContent = active ? '🔊 SFX' : '🔇 SFX';
    });

    this._btnCollapse.addEventListener('click', () => {
      this.classList.toggle('collapsed');
    });
  }

  interrupt() {
    this._interrupted = true;
    this.turnQueue = [];
  }

  addTurn(turn) {
    if (!turn || !turn.text) return;
    const clean = turn.text.trim();
    if (!clean) return;
    if (this._currentText === clean || this._lastFinishedText === clean) return;
    if (this.turnQueue.some(q => q.text && q.text.trim() === clean)) return;

    if (turn.phase === 'objection') {
      // Objection interrupts any active speaker immediately!
      this._interrupted = true;
      this.turnQueue = [turn];
      if (!this.isTyping) {
        this._processQueue();
      }
      return;
    }

    this.turnQueue.push(turn);
    if (!this.isTyping) {
      this._processQueue();
    }
  }

  clear() {
    this.turnQueue = [];
    this._currentText = null;
    this._lastFinishedText = null;
    this._interrupted = false;
    if (this._container) this._container.innerHTML = '';
  }

  async _processQueue() {
    if (this.turnQueue.length === 0) {
      this.isTyping = false;
      this._currentText = null;
      return;
    }

    this.isTyping = true;
    const turn = this.turnQueue.shift();
    this._currentText = turn.text ? turn.text.trim() : null;
    await this._typeTurn(turn);
    this._lastFinishedText = this._currentText;
    this._currentText = null;
    this._processQueue();
  }

  async _typeTurn(turn) {
    const { voice_id, role, phase, text } = turn;
    const cleanText = (text || '').trim();
    if (!cleanText) return;

    this._interrupted = false;

    if (phase === 'objection') {
      const objDiv = document.createElement('div');
      objDiv.className = 'objection-banner';
      objDiv.textContent = '⚡ ¡OBJECIÓN EN SALA! ⚡';
      this._container.appendChild(objDiv);
      this.sound.playReturn();
      this._scrollToBottom();
    }

    const entryDiv = document.createElement('div');
    entryDiv.className = 'transcript-entry';

    const headerDiv = document.createElement('div');
    headerDiv.className = `entry-header ${voice_id || ''}`;
    const vname = (voice_id || 'KATETO').toUpperCase();
    const pLabel = (phase || 'ARGUMENTO').toUpperCase();
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    headerDiv.textContent = `[${timeStr}] ${vname} • ${pLabel}`;

    const bodySpan = document.createElement('span');
    bodySpan.className = 'entry-text';

    const cursor = document.createElement('span');
    cursor.className = 'typewriter-cursor';

    entryDiv.appendChild(headerDiv);
    entryDiv.appendChild(bodySpan);
    entryDiv.appendChild(cursor);
    this._container.appendChild(entryDiv);
    this._scrollToBottom();

    // Type character by character with organic mechanical cadence
    for (let i = 0; i < cleanText.length; i++) {
      if (this._interrupted) {
        bodySpan.textContent += ' [INTERRUMPIDO]';
        break;
      }

      const ch = cleanText[i];
      bodySpan.textContent += ch;

      // Play click sound on non-whitespace characters
      if (!/\s/.test(ch)) {
        this.sound.playClick();
      }

      // Scrolling
      if (i % 8 === 0 || ch === '\n') {
        this._scrollToBottom();
      }

      // Timing delay calibrated to match subtitle speed (~190 WPM, ~50ms per character)
      let delay = 48;
      if (ch === '.' || ch === '!' || ch === '?') {
        delay = 220;
        this.sound.playReturn();
      } else if (ch === ',' || ch === ';') {
        delay = 110;
      } else if (ch === ' ') {
        delay = 55;
      }

      await new Promise((resolve) => setTimeout(resolve, delay));
    }

    // Turn complete: carriage return sound and finalize cursor
    this.sound.playReturn();
    cursor.remove();
    this._scrollToBottom();
  }

  _scrollToBottom() {
    if (this._body) {
      this._body.scrollTop = this._body.scrollHeight;
    }
  }
}

if (!customElements.get('kateto-paper-transcript')) {
  customElements.define('kateto-paper-transcript', KatetoPaperTranscript);
}
