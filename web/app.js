/**
 * Kateto Web Sandbox — Dashboard UI
 *
 * Vanilla JS (ponytail: no framework needed for an info dashboard).
 * Connects to a Kateto instance via WebSocket when available;
 * falls back to mock data for standalone presentation.
 */

/* ------------------------------------------------------------------ */
/*  Data                                                               */
/* ------------------------------------------------------------------ */

const CAPABILITIES = [
  {
    icon: '🎙️',
    title: 'Voice Interaction',
    desc: 'Speak to Jane, Doktor, or Conquest. Transcription, classification, generation, and TTS loop in real time.',
  },
  {
    icon: '🧩',
    title: 'Plugin Architecture',
    desc: 'Event-driven plugin system. Audio I/O, executors, connectors, and system plugins communicate via a shared bus.',
  },
  {
    icon: '📋',
    title: 'Backlog Management',
    desc: 'Create, prioritize, and track work items with Must/Should/Could/Won\'t. Filter by status or priority.',
  },
  {
    icon: '🔄',
    title: 'Workflow Engine',
    desc: 'Declarative multi-phase workflows with checkpoints. Perfect for sprint planning, standups, and retrospectives.',
  },
  {
    icon: '🔧',
    title: 'MCP Integration',
    desc: 'Model Context Protocol servers for tools, memory, and external service integration. Extend via config.toml.',
  },
  {
    icon: '⚡',
    title: 'Hot Reload',
    desc: 'Watchdog-based hot reload of plugins, voices, and config. Change code without restarting the runtime.',
  },
];

const VOICES = [
  {
    name: 'Jane',
    role: 'Orchestrator',
    status: 'idle',
    color: 'var(--accent)',
    desc: 'Coordinates the team, delegates tasks, manages conversation flow.',
  },
  {
    name: 'Doktor',
    role: 'Analyst & Backlog',
    status: 'idle',
    color: 'var(--purple)',
    desc: 'Planning, risk analysis, backlog grooming, and structured thinking.',
  },
  {
    name: 'Conquest',
    role: 'Facilitator',
    status: 'idle',
    color: 'var(--orange)',
    desc: 'Agile ceremonies, sprint execution, standups, and retrospectives.',
  },
];

const MOCK_EVENTS = [
  { tag: 'TRANSCRIPTION', text: '"plan tomorrow standup"', highlight: true },
  { tag: 'CLASSIFICATION', text: 'category=EXECUTE confidence=0.94', highlight: false },
  { tag: 'GENERATE', text: 'Conquest · planning standup agenda', highlight: true },
  { tag: 'STREAM_RESPONSE', text: 'Starting standup session for tomorrow…', highlight: false },
  { tag: 'AUDIO_CHUNK', text: 'voice=conquest sequence=3 final=false', highlight: false },
];

/* ------------------------------------------------------------------ */
/*  State                                                              */
/* ------------------------------------------------------------------ */

const state = {
  ws: null,
  connected: false,
  sandboxReady: false,
};

/* ------------------------------------------------------------------ */
/*  DOM refs                                                           */
/* ------------------------------------------------------------------ */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

/* ------------------------------------------------------------------ */
/*  Render                                                             */
/* ------------------------------------------------------------------ */

function renderCapabilities() {
  const grid = document.getElementById('capabilitiesGrid');
  grid.innerHTML = CAPABILITIES.map(
    (c) => `
      <div class="card">
        <div class="card-icon">${c.icon}</div>
        <h3>${c.title}</h3>
        <p>${c.desc}</p>
      </div>`
  ).join('');
}

function renderVoices() {
  const grid = document.getElementById('voicesGrid');
  grid.innerHTML = VOICES.map(
    (v) => `
      <div class="voice-card">
        <div class="voice-name" style="color: ${v.color}">${v.name}</div>
        <div class="voice-role">${v.role}</div>
        <div class="voice-status-row">
          <span class="status-dot idle"></span>
          <span>${v.desc}</span>
        </div>
      </div>`
  ).join('');
}

function updateSystemStatus(online) {
  const dot = document.getElementById('systemDot');
  const label = document.getElementById('systemStatus');
  dot.className = `status-dot ${online ? 'online' : 'offline'}`;
  label.textContent = online ? 'Connected' : 'Disconnected';
}

function updateVoicesCount(active) {
  document.getElementById('voicesOnline').textContent = active;
}

function updateSandboxButton(ready) {
  const btn = document.getElementById('btnSandbox');
  btn.disabled = !ready;
  btn.textContent = ready ? '▶ Launch Sandbox' : '⏳ Connecting…';
  state.sandboxReady = ready;
}

function updateWSIndicator(mode) {
  const el = document.getElementById('wsIndicator');
  el.textContent = mode === 'ws'
    ? '🔗 WebSocket connected'
    : '⚡ Standalone mode';
}

function addEventEntry(tag, text, highlight) {
  const stream = document.getElementById('eventStream');
  const placeholder = stream.querySelector('.placeholder');
  if (placeholder) placeholder.remove();

  const entry = document.createElement('div');
  entry.className = 'event-entry';
  entry.innerHTML = `
    <span class="event-tag">${tag}</span>
    <span class="event-text${highlight ? ' highlight' : ''}">${escapeHtml(text)}</span>
  `;
  stream.appendChild(entry);
  stream.scrollTop = stream.scrollHeight;

  // keep last 50 entries
  while (stream.children.length > 50) stream.removeChild(stream.firstChild);
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function loadMockEvents() {
  MOCK_EVENTS.forEach((e, i) => {
    setTimeout(() => addEventEntry(e.tag, e.text, e.highlight), i * 600);
  });
}

/* ------------------------------------------------------------------ */
/*  WebSocket                                                          */
/* ------------------------------------------------------------------ */

function connectWebSocket(url) {
  if (state.ws) state.ws.close();

  try {
    state.ws = new WebSocket(url);
  } catch {
    console.log('[WS] Invalid URL, staying in standalone mode');
    updateWSIndicator('standalone');
    loadMockEvents();
    updateSystemStatus(false);
    updateSandboxButton(false);
    return;
  }

  state.ws.onopen = () => {
    console.log('[WS] connected');
    state.connected = true;
    updateSystemStatus(true);
    updateWSIndicator('ws');
    updateSandboxButton(true);
    const btn = document.getElementsByClassName('event-stream')  // clear mock placeholder
    addEventEntry('SYSTEM', 'WebSocket connected to Kateto runtime', true);
  };

  state.ws.onclose = () => {
    state.connected = false;
    updateSystemStatus(false);
    updateWSIndicator('standalone');
    updateSandboxButton(false);
    addEventEntry('SYSTEM', 'WebSocket disconnected', false);
  };

  state.ws.onerror = () => {
    addEventEntry('ERROR', 'WebSocket connection error', false);
  };

  state.ws.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data);
      addEventEntry(ev.type || 'EVENT', ev.data || msg.data, true);
    } catch {
      addEventEntry('RAW', msg.data, false);
    }
  };
}

/* ------------------------------------------------------------------ */
/*  Init                                                               */
/* ------------------------------------------------------------------ */

document.addEventListener('DOMContentLoaded', () => {
  renderCapabilities();
  renderVoices();

  // Detect backend from meta or default to standalone
  const wsUrl = document.querySelector('meta[name="kateto-ws"]')?.content;

  if (wsUrl) {
    connectWebSocket(wsUrl);
  } else {
    // Standalone demo mode
    updateSystemStatus(false);
    updateWSIndicator('standalone');
    updateVoicesCount(0);
    updateSandboxButton(false);
    loadMockEvents();
  }

  // Refresh button
  document.getElementById('btnRefresh').addEventListener('click', () => {
    if (state.ws && state.connected) {
      state.ws.send(JSON.stringify({ type: 'ping' }));
    } else {
      // re-run mock for demo
      const stream = document.getElementById('eventStream');
      stream.innerHTML = '';
      loadMockEvents();
    }
  });

  // Sandbox button
  document.getElementById('btnSandbox').addEventListener('click', () => {
    if (state.connected && state.ws) {
      state.ws.send(JSON.stringify({ type: 'sandbox_start' }));
      addEventEntry('SANDBOX', 'Launching sandbox environment…', true);
    }
  });

  // Setup guide link
  document.getElementById('setupGuideLink').addEventListener('click', (e) => {
    e.preventDefault();
    addEventEntry('INFO', 'See web/PLAN.md for backend setup instructions', false);
  });
});
