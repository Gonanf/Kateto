// Tests de la cinemática del jaw del overlay (bugs 112 y 125).
//
// Convención única: jawOffsetY NEGATIVO = la capa de ARRIBA sube = boca que
// abre, neutro = 0 = cerrada (bug 125: avatar_jaw.png es la mitad superior).
// El ciclo abre/cierra es unipolar (max..0): la mandíbula no puede ir "más
// cerrada que cerrada", así que los ciclos se cuentan por cruces del nivel
// medio (2 por ciclo abre/cierra) y el retorno físico al neutro se verifica
// con max ≈ 0. Corre con: node --test kateto-avatar.test.mjs

// Stubs mínimos de DOM (el módulo registra Custom Elements a nivel top-level,
// pero lo testeado aquí son funciones puras que no tocan el DOM).
globalThis.HTMLElement = class HTMLElement {};
globalThis.customElements = { get: () => undefined, define: () => {} };

import { describe, it } from "node:test";
import assert from "node:assert/strict";

const mod = await import("./kateto-avatar.js");
const {
  computeJawKinematics,
  computeBackendKinematics,
  JAW_MAX_TRAVEL_PX,
  IdleMotion,
  combineIdleWithVoice,
  IDLE_TURN_PERIOD_MS,
  IDLE_TILT_DEG,
  IDLE_SWAY_PX,
  IDLE_EASE_TAU_MS,
  IDLE_SPEAKING_SCALE,
} = mod;

// RNG determinista (mulberry32) y avance de tiempo fijo, como en fix-112.
function makeRng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

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

  it("durante el habla el máximo es ≈ 0 y el mínimo < 0 (sin piso fijo)", () => {
    const ys = speechSeries();
    assert.ok(Math.max(...ys) > -1.0, `max debería volver al neutro, fue ${Math.max(...ys)}`);
    assert.ok(Math.min(...ys) < -20.0, `min debería subir la capa con punch, fue ${Math.min(...ys)}`);
    assert.ok(ys.every((y) => y <= 0), "convención unipolar: nunca positivo");
  });

  it("hay ciclo abre/cierra real: >= 4 cruces del nivel medio en 1 s", () => {
    const ys = speechSeries();
    const crosses = midCrossings(ys);
    assert.ok(crosses >= 4, `se esperaban >= 4 cruces (2 por ciclo), hubo ${crosses}`);
  });

  it("respeta el recorrido máximo del backend (<= 32 px hacia arriba)", () => {
    const ys = speechSeries();
    assert.ok(Math.min(...ys) >= -JAW_MAX_TRAVEL_PX, `min ${Math.min(...ys)} < ${-JAW_MAX_TRAVEL_PX}`);
  });

  it("tilt acotado a ±6.5° (antes llegaba a ±40°)", () => {
    for (let i = 0; i < 200; i++) {
      const { jawRotation } = computeJawKinematics(0.8, i * 17);
      assert.ok(Math.abs(jawRotation) <= 6.5, `tilt ${jawRotation} excede ±6.5°`);
    }
  });

  it("más energía ⇒ más subida (escala agresiva, bug 122)", () => {
    const peak = (rms) => {
      const ys = [];
      for (let i = 0; i < 60; i++) ys.push(computeJawKinematics(rms, i * 17).jawOffsetY);
      return Math.min(...ys);
    };
    const low = peak(0.15);
    const high = peak(0.8);
    assert.ok(high < low * 1.5, `voz fuerte (${high}) debería superar ampliamente a voz baja (${low})`);
    assert.ok(high <= -24.0, `voz fuerte debería acercarse al tope, fue ${high}`);
  });

  it("silencio ⇒ 0 exacto (sin residuo, bug 122)", () => {
    for (const rms of [0, 0.005, 0.014, -0.3]) {
      assert.deepEqual(computeJawKinematics(rms, 999), { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0 });
    }
  });
});

describe("convención compartida local vs backend", () => {
  it("mismo signo: ambos <= 0 en jaw, head >= 0", () => {
    for (const rms of [0.1, 0.3, 0.5, 0.8, 1.0]) {
      const ys = [];
      for (let i = 0; i < 60; i++) ys.push(computeJawKinematics(rms, i * 17).jawOffsetY);
      const back = computeBackendKinematics(rms);
      assert.ok(back.jawOffsetY < 0, `backend debería abrir con rms=${rms}`);
      assert.ok(Math.min(...ys) < 0, `local debería abrir con rms=${rms}`);
      assert.ok(ys.every((y) => y <= 0) && back.jawOffsetY <= 0, "mismo signo en jaw");
      assert.ok(back.headOffsetY >= 0, "head baja para ayudar a abrir");
    }
  });

  it("silencio cierra en ambos paths", () => {
    const back = computeBackendKinematics(0.04);
    assert.deepEqual(back, { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0, headOffsetY: 0 });
  });
});

describe("idle motion (issue 128: rotación nueva cada segundo, se mueve hacia ahí)", () => {
  function runIdle(seed, dtMs = 50, totalMs = 8000) {
    const idle = new IdleMotion({ rng: makeRng(seed) });
    const frames = [];
    for (let t = 0; t <= totalMs; t += dtMs) {
      frames.push({ t, pose: idle.update(t) });
    }
    return { idle, frames };
  }

  it("el objetivo cambia al menos una vez por segundo (poses distintas cada segundo, t=0..6s)", () => {
    const idle = new IdleMotion({ rng: makeRng(42) });
    const poses = [];
    for (let k = 0; k <= 6; k++) {
      const t = k * IDLE_TURN_PERIOD_MS + 600; // dentro del turno k (ya eased)
      poses.push(idle.update(t));
    }
    let changed = 0;
    for (let i = 1; i < poses.length; i++) {
      const dr = Math.abs(poses[i].jawRotation - poses[i - 1].jawRotation);
      const dx = Math.abs(poses[i].jawOffsetX - poses[i - 1].jawOffsetX);
      if (dr > 0.5 || dx > 0.5) changed++;
    }
    assert.ok(changed >= 5, `el objetivo debería cambiar cada segundo; cambió ${changed}/6`);
  });

  it("rotación dentro de ±IDLE_TILT_DEG, sway dentro de ±IDLE_SWAY_PX, mismo signo", () => {
    const { frames } = runIdle(7);
    for (const { pose } of frames) {
      assert.ok(Math.abs(pose.jawRotation) <= IDLE_TILT_DEG, `rot ${pose.jawRotation} fuera de rango`);
      assert.ok(Math.abs(pose.jawOffsetX) <= IDLE_SWAY_PX, `sway ${pose.jawOffsetX} fuera de rango`);
      if (Math.abs(pose.jawRotation) > 0.01) {
        assert.equal(Math.sign(pose.jawRotation), Math.sign(pose.jawOffsetX), "sway debe mirar hacia la rotación");
      }
    }
  });

  it("el acercamiento es suave (sin saltos entre frames de ~50 ms)", () => {
    const { frames } = runIdle(99);
    for (let i = 1; i < frames.length; i++) {
      const dr = Math.abs(frames[i].pose.jawRotation - frames[i - 1].pose.jawRotation);
      const dx = Math.abs(frames[i].pose.jawOffsetX - frames[i - 1].pose.jawOffsetX);
      assert.ok(dr < 2.0, `salto de rotación ${dr}° en un frame`);
      assert.ok(dx < 3.5, `salto de sway ${dx}px en un frame`);
    }
  });

  it("converge al objetivo dentro de cada turno (sin oscilar de más)", () => {
    const idle = new IdleMotion({ rng: makeRng(5) });
    // Dentro de un turno el objetivo es fijo: la distancia a él debe decrecer.
    idle.update(0);
    let prevDist = Infinity;
    for (let t = 50; t <= IDLE_TURN_PERIOD_MS - 50; t += 50) {
      const pose = idle.update(t);
      const tgt = idle.target;
      const dist = Math.hypot(pose.jawRotation - tgt.rotation, pose.jawOffsetX - tgt.sway);
      assert.ok(dist <= prevDist + 1e-9, `distancia al objetivo creció: ${prevDist} → ${dist}`);
      prevDist = dist;
    }
    assert.ok(prevDist < IDLE_TILT_DEG, "debería estar acercándose al objetivo");
  });

  it("en silencio jawOffsetY === 0 exacto con el idle andando", () => {
    const { frames } = runIdle(11);
    for (const { pose } of frames) {
      assert.equal(pose.jawOffsetY, 0, "el idle nunca debe abrir la boca");
    }
    // Combinado con voz silenciosa: sigue 0 exacto (bug 112).
    const idle = new IdleMotion({ rng: makeRng(11) });
    const idlePose = idle.update(2500);
    const combined = combineIdleWithVoice(idlePose, computeJawKinematics(0, 2500), false);
    assert.equal(combined.jawOffsetY, 0);
  });

  it("hablando, el idle aparece escalado por IDLE_SPEAKING_SCALE", () => {
    const idle = new IdleMotion({ rng: makeRng(21) });
    const idlePose = idle.update(3500);
    const voice = computeJawKinematics(0.5, 3500);
    const combined = combineIdleWithVoice(idlePose, voice, true);
    assert.ok(Math.abs(combined.jawOffsetX - (voice.jawOffsetX + idlePose.jawOffsetX * IDLE_SPEAKING_SCALE)) < 1e-9);
    assert.ok(Math.abs(combined.jawRotation - (voice.jawRotation + idlePose.jawRotation * IDLE_SPEAKING_SCALE)) < 1e-9);
    // La boca sigue siendo la protagonista: el aporte idle de Y es cero y el
    // jawOffsetY de la voz no se toca.
    assert.equal(combined.jawOffsetY, voice.jawOffsetY);
    assert.ok(combined.jawOffsetY < 0);
  });

  it("en silencio el idle va a plena amplitud (sin escala)", () => {
    const idle = new IdleMotion({ rng: makeRng(31) });
    const idlePose = idle.update(4500);
    const combined = combineIdleWithVoice(idlePose, computeJawKinematics(0, 4500), false);
    assert.ok(Math.abs(combined.jawOffsetX - idlePose.jawOffsetX) < 1e-9);
    assert.ok(Math.abs(combined.jawRotation - idlePose.jawRotation) < 1e-9);
    assert.equal(combined.jawOffsetY, 0);
  });
});
