// Tests del módulo offline del overlay (estado + badge + TTS local).
// Sin jsdom: los fakes de doc/speech se escriben a mano.
// Corre con: node --test kateto-offline.test.mjs

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  OFFLINE_FAILURE_THRESHOLD,
  createOfflineState,
  reduceOffline,
  createOfflineShell,
} from "./kateto-offline.js";

describe("reduceOffline", () => {
  it("reduceOffline: un ws_close incrementa failures y sigue online", () => {
    // Given: un estado inicial online.
    const state = createOfflineState();

    // When: llega un solo cierre de socket.
    const next = reduceOffline(state, { type: "ws_close" });

    // Then: suma un failure y no entra en offline.
    assert.equal(next.failures, 1);
    assert.equal(next.offline, false);
  });

  it("reduceOffline: el tercer ws_close consecutivo entra en offline", () => {
    // Given: dos cierres consecutivos (umbral - 1).
    let state = createOfflineState();
    state = reduceOffline(state, { type: "ws_close" });
    state = reduceOffline(state, { type: "ws_close" });
    assert.equal(state.offline, false);

    // When: llega el tercero.
    state = reduceOffline(state, { type: "ws_close" });

    // Then: se cruza el umbral.
    assert.equal(state.failures, OFFLINE_FAILURE_THRESHOLD);
    assert.equal(state.offline, true);
  });

  it("reduceOffline: un ws_open resetea failures y sale de offline", () => {
    // Given: un estado offline por tres cierres.
    let state = createOfflineState();
    state = reduceOffline(state, { type: "ws_close" });
    state = reduceOffline(state, { type: "ws_close" });
    state = reduceOffline(state, { type: "ws_close" });
    assert.equal(state.offline, true);

    // When: el socket vuelve a abrirse.
    state = reduceOffline(state, { type: "ws_open" });

    // Then: todo vuelve al default.
    assert.equal(state.failures, 0);
    assert.equal(state.offline, false);
  });

  it("reduceOffline: no muta el estado de entrada", () => {
    // Given: un estado de entrada.
    const state = { failures: 2, offline: false };
    const snapshot = { ...state };

    // When: se reduce un evento.
    const next = reduceOffline(state, { type: "ws_close" });

    // Then: el estado de entrada queda igual y el resultado es otro objeto.
    assert.deepEqual(state, snapshot);
    assert.notEqual(next, state);
    assert.equal(next.failures, 3);
  });
});

describe("createOfflineShell", () => {
  it("createOfflineShell: speak usa es-AR y devuelve true", () => {
    // Given: un shell con un speechSynthesis de mentira.
    const spoken = [];
    class FakeUtterance {
      constructor(text) {
        this.text = text;
      }
    }
    globalThis.SpeechSynthesisUtterance = FakeUtterance;
    try {
      const shell = createOfflineShell({
        doc: null,
        speech: {
          cancel() {},
          speak(u) {
            spoken.push(u);
          },
        },
      });

      // When: se pide hablar.
      const ok = shell.speak("kateto está offline");

      // Then: habló, en español rioplatense, a velocidad normal.
      assert.equal(ok, true);
      assert.equal(spoken.length, 1);
      assert.equal(spoken[0].lang, "es-AR");
      assert.equal(spoken[0].rate, 1.0);
      assert.equal(spoken[0].text, "kateto está offline");
    } finally {
      delete globalThis.SpeechSynthesisUtterance;
    }
  });

  it("createOfflineShell: sin speechSynthesis speak devuelve false y no lanza", () => {
    // Given: un shell sin speech.
    const shell = createOfflineShell({ doc: null, speech: undefined });
    const shellDefault = createOfflineShell();

    // When/Then: speak devuelve false sin tirar.
    assert.equal(shell.speak("hola"), false);
    assert.equal(shellDefault.speak("hola"), false);
    assert.equal(shell.isOffline(), false);
  });

  it("createOfflineShell: update marca el badge visible solo en offline", () => {
    // Given: un doc fake con el badge oculto.
    const badge = { hidden: true };
    const toggles = [];
    const doc = {
      body: {
        classList: {
          toggle(name, on) {
            toggles.push([name, on]);
          },
        },
      },
      getElementById: () => badge,
    };
    const shell = createOfflineShell({ doc });

    // When: dos fallos seguidos -> sigue online.
    shell.update({ type: "ws_close" });
    shell.update({ type: "ws_close" });
    // Then: el badge sigue oculto.
    assert.equal(badge.hidden, true);

    // When: el tercer fallo cruza el umbral.
    shell.update({ type: "ws_close" });
    // Then: el badge se vuelve visible.
    assert.equal(badge.hidden, false);
    assert.equal(shell.isOffline(), true);

    // When: el socket vuelve.
    shell.update({ type: "ws_open" });
    // Then: el badge desaparece.
    assert.equal(badge.hidden, true);
    assert.equal(shell.isOffline(), false);
    assert.deepEqual(toggles[toggles.length - 1], ["offline", false]);
  });
});
