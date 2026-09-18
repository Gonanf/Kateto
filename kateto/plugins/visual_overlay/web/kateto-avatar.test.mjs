// Tests de la cinemática del jaw del overlay (bug 112).
//
// Convención única: jawOffsetY POSITIVO = boca que abre, neutro = 0 = cerrada.
// El ciclo abre/cierra es unipolar (0..max): la mandíbula no puede ir "más
// cerrada que cerrada", así que los ciclos se cuentan por cruces del nivel
// medio (2 por ciclo abre/cierra) y el retorno físico al neutro se verifica
// con min ≈ 0. Corre con: node --test kateto-avatar.test.mjs

// Stubs mínimos de DOM (el módulo registra Custom Elements a nivel top-level,
// pero lo testeado aquí son funciones puras que no tocan el DOM).
globalThis.HTMLElement = class HTMLElement {};
globalThis.customElements = { get: () => undefined, define: () => {} };

import { describe, it } from "node:test";
import assert from "node:assert/strict";

const mod = await import("./kateto-avatar.js");
const { computeJawKinematics, computeBackendKinematics, JAW_MAX_TRAVEL_PX } = mod;

function speechSeries() {
  const seq = [0.2, 0.5, 0.8];
  const ys = [];
  for (let i = 0; i < 60; i++) {
    ys.push(computeJawKinematics(seq[i % seq.length], Math.round((i * 1000) / 60)).jawOffsetY);
  }
  return ys;
}

function midCrossings(ys) {
  const mid = (Math.min(...ys) + Math.max(...ys)) / 2;
  let n = 0;
  for (let i = 1; i < ys.length; i++) {
    if ((ys[i - 1] - mid) * (ys[i] - mid) < 0) n++;
  }
  return n;
}

describe("computeJawKinematics (bug 112: ciclo abre/cierra, no solo arriba)", () => {
  it("con rms 0 devuelve exactamente el neutro", () => {
    assert.deepEqual(computeJawKinematics(0, 12345), { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0 });
    assert.deepEqual(computeJawKinematics(0.014, 12345), { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0 });
  });

  it("durante el habla el mínimo es ≈ 0 y el máximo > 0 (sin piso fijo)", () => {
    const ys = speechSeries();
    assert.ok(Math.min(...ys) < 1.0, `min debería volver al neutro, fue ${Math.min(...ys)}`);
    assert.ok(Math.max(...ys) > 20.0, `max debería abrir la boca con punch, fue ${Math.max(...ys)}`);
    assert.ok(ys.every((y) => y >= 0), "convención unipolar: nunca negativo");
  });

  it("hay ciclo abre/cierra real: >= 4 cruces del nivel medio en 1 s", () => {
    const ys = speechSeries();
    const crosses = midCrossings(ys);
    assert.ok(crosses >= 4, `se esperaban >= 4 cruces (2 por ciclo), hubo ${crosses}`);
  });

  it("respeta el recorrido máximo del backend (<= 32 px)", () => {
    const ys = speechSeries();
    assert.ok(Math.max(...ys) <= JAW_MAX_TRAVEL_PX, `max ${Math.max(...ys)} > ${JAW_MAX_TRAVEL_PX}`);
  });

  it("tilt acotado a ±6.5° (antes llegaba a ±40°)", () => {
    for (let i = 0; i < 200; i++) {
      const { jawRotation } = computeJawKinematics(0.8, i * 17);
      assert.ok(Math.abs(jawRotation) <= 6.5, `tilt ${jawRotation} excede ±6.5°`);
    }
  });

  it("más energía ⇒ más recorrido (escala agresiva, bug 122)", () => {
    const peak = (rms) => {
      const ys = [];
      for (let i = 0; i < 60; i++) ys.push(computeJawKinematics(rms, i * 17).jawOffsetY);
      return Math.max(...ys);
    };
    const low = peak(0.15);
    const high = peak(0.8);
    assert.ok(high > low * 1.5, `voz fuerte (${high}) debería superar ampliamente a voz baja (${low})`);
    assert.ok(high >= 24.0, `voz fuerte debería acercarse al tope, fue ${high}`);
  });

  it("silencio ⇒ 0 exacto (sin residuo, bug 122)", () => {
    for (const rms of [0, 0.005, 0.014, -0.3]) {
      assert.deepEqual(computeJawKinematics(rms, 999), { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0 });
    }
  });
});

describe("convención compartida local vs backend", () => {
  it("mismo signo: ambos >= 0 en jaw, head <= 0", () => {
    for (const rms of [0.1, 0.3, 0.5, 0.8, 1.0]) {
      const ys = [];
      for (let i = 0; i < 60; i++) ys.push(computeJawKinematics(rms, i * 17).jawOffsetY);
      const back = computeBackendKinematics(rms);
      assert.ok(back.jawOffsetY > 0, `backend debería abrir con rms=${rms}`);
      assert.ok(Math.max(...ys) > 0, `local debería abrir con rms=${rms}`);
      assert.ok(ys.every((y) => y >= 0) && back.jawOffsetY >= 0, "mismo signo en jaw");
      assert.ok(back.headOffsetY <= 0, "head compensa en sentido opuesto");
    }
  });

  it("silencio cierra en ambos paths", () => {
    const back = computeBackendKinematics(0.04);
    assert.deepEqual(back, { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0, headOffsetY: 0 });
  });
});
