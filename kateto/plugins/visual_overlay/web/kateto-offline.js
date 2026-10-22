// Estado offline del overlay (fallback local cuando Kateto no responde).
//
// Módulo ES sin DOM a nivel top-level: todo llega por parámetros
// ({ doc, speech }) para poder testearlo con fakes hechos a mano.
// Cero URLs externas, cero dependencias.

export const OFFLINE_FAILURE_THRESHOLD = 3;

export function createOfflineState() {
  return { failures: 0, offline: false };
}

// Puro: devuelve un estado NUEVO, nunca muta `state`.
export function reduceOffline(state, event) {
  const failures = Number.isFinite(state && state.failures) ? state.failures : 0;
  const type = event && event.type;

  if (type === 'ws_open') {
    return { failures: 0, offline: false };
  }
  if (type === 'ws_close' || type === 'ws_error') {
    const next = failures + 1;
    return { failures: next, offline: next >= OFFLINE_FAILURE_THRESHOLD };
  }
  // Evento desconocido -> estado equivalente sin cambios.
  return { failures, offline: Boolean(state && state.offline) };
}

export function createOfflineShell({ doc, speech } = {}) {
  let state = createOfflineState();

  function runApply() {
    try {
      if (doc && typeof doc.getElementById === 'function') {
        const badge = doc.getElementById('offline-badge');
        if (badge) badge.hidden = !state.offline;
      }
      const body = doc && doc.body;
      if (body && body.classList && typeof body.classList.toggle === 'function') {
        body.classList.toggle('offline', state.offline);
      }
    } catch {
      // doc puede ser nulo/parcial: nunca tirar.
    }
  }

  return {
    update(event) {
      state = reduceOffline(state, event);
      runApply();
      return { ...state };
    },
    apply() {
      runApply();
      return { ...state };
    },
    isOffline() {
      return Boolean(state.offline);
    },
    speak(text) {
      if (!speech || typeof speech.speak !== 'function') return false;
      try {
        if (typeof speech.cancel === 'function') speech.cancel();
        const Utterance = globalThis.SpeechSynthesisUtterance;
        if (typeof Utterance !== 'function') return false;
        const u = new Utterance(text);
        u.lang = 'es-AR';
        u.rate = 1.0;
        speech.speak(u);
        return true;
      } catch {
        return false;
      }
    },
    stopSpeaking() {
      try {
        if (speech && typeof speech.cancel === 'function') speech.cancel();
      } catch {
        // best-effort
      }
    },
  };
}
