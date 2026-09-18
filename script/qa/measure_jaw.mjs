// Medición QA del jaw del overlay (bugs 112/122/125).
//
// Convención (bug 125): jawOffsetY NEGATIVO = la capa de ARRIBA sube = abre;
// headOffsetY POSITIVO leve = la pieza de abajo baja = ayuda a abrir.
//
// Protocolo (pedido en el issue):
//   1. silencio (rms 0) ~0.3 s,
//   2. habla (secuencia rms 0.2/0.5/0.8) ~1.5 s,
//   3. silencio otra vez ~0.4 s.
// Muestreo a ~60 Hz del `jawOffsetY` computado por computeJawKinematics
// (el mismo valor que setRms vuelca en `style.transform` de la capa jaw).
// Además compara contra computeBackendKinematics (path backend) con el mismo rms.
//
// Uso: node script/qa/measure_jaw.mjs
// Uso browser (mismo protocolo en Chromium real): ver jaw_harness.html.
//
// Los stats de jawOffsetY son deterministas (Math.random sólo afecta X/tilt).

// Stubs mínimos de DOM: el módulo define Custom Elements a nivel top-level,
// pero las funciones medidas son puras y no tocan el DOM.
globalThis.HTMLElement = class HTMLElement {};
globalThis.customElements = { get: () => undefined, define: () => {} };

const modPath = new URL(
  "../../kateto/plugins/visual_overlay/web/kateto-avatar.js",
  import.meta.url,
).href;
const { computeJawKinematics, computeBackendKinematics, IdleMotion } = await import(modPath);

// RNG determinista para la serie idle (mulberry32).
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

const DT_MS = 1000 / 60;
const rmsSeq = [0.2, 0.5, 0.8];

function buildSignal() {
  const samples = [];
  let t = 0;
  const push = (durMs, rmsFn) => {
    const n = Math.round(durMs / DT_MS);
    for (let i = 0; i < n; i++) {
      samples.push({ t: Math.round(t), rms: rmsFn(samples.length) });
      t += DT_MS;
    }
  };
  push(300, () => 0.0); // silencio inicial
  const speechStart = samples.length;
  push(1500, (idx) => rmsSeq[(idx - speechStart) % rmsSeq.length]); // habla
  const speechEnd = samples.length;
  push(400, () => 0.0); // silencio final
  return { samples, speechStart, speechEnd };
}

function stats(vals) {
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const neg = vals.filter((v) => v < 0).length;
  const pos = vals.filter((v) => v > 0).length;
  const zero = vals.filter((v) => v === 0).length;
  return { n: vals.length, min, max, mean, neg, pos, zero };
}

// Cruces del neutro: cambios de signo entre muestras consecutivas,
// contando también toques exactos de 0 como retorno al neutro.
function zeroCrossings(vals) {
  let crosses = 0;
  for (let i = 1; i < vals.length; i++) {
    const a = vals[i - 1];
    const b = vals[i];
    if (a === 0 && b !== 0) crosses++;
    else if (b === 0 && a !== 0) crosses++;
    else if (a < 0 && b > 0) crosses++;
    else if (a > 0 && b < 0) crosses++;
  }
  return crosses;
}

// Cruces de nivel medio de la serie de habla (nivel = (min+max)/2, misma
// convención que midCrossings en kateto-avatar.test.mjs).
function midCrossings(vals) {
  const mid = (Math.min(...vals) + Math.max(...vals)) / 2;
  let n = 0;
  for (let i = 1; i < vals.length; i++) {
    if ((vals[i - 1] - mid) * (vals[i] - mid) < 0) n++;
  }
  return n;
}

const { samples, speechStart, speechEnd } = buildSignal();
const localY = samples.map((s) => computeJawKinematics(s.rms, s.t).jawOffsetY);
const backendY = samples.map((s) => computeBackendKinematics(s.rms).jawOffsetY);

const speechLocal = localY.slice(speechStart, speechEnd);
const speechBackend = backendY.slice(speechStart, speechEnd);
const silenceEnd = localY.slice(speechEnd);

const sLocal = stats(speechLocal);
const sBackend = stats(speechBackend);

// Salto entre paths con el mismo rms (convenciones opuestas saltan).
let maxJump = 0;
for (let i = speechStart; i < speechEnd; i++) {
  maxJump = Math.max(maxJump, Math.abs(localY[i] - backendY[i]));
}

// --- Serie idle (issue 128): rotación y sway muestreados cada 100 ms por 6 s,
// con el objetivo sorteado de cada segundo. Corre en silencio (sin RMS): es
// movimiento de render, no depende de la voz.
function buildIdleSeries() {
  const idle = new IdleMotion({ rng: makeRng(2026) });
  const samples = [];
  for (let t = 0; t <= 6000; t += 100) {
    const pose = idle.update(t);
    samples.push({
      t,
      turn: Math.floor(t / 1000),
      targetRotation: Number(idle.target.rotation.toFixed(2)),
      targetSway: Number(idle.target.sway.toFixed(2)),
      jawRotation: Number(pose.jawRotation.toFixed(2)),
      jawOffsetX: Number(pose.jawOffsetX.toFixed(2)),
      jawOffsetY: pose.jawOffsetY,
    });
  }
  // Resumen por segundo: objetivo sorteado y pose al final del turno.
  const perSecond = samples
    .filter((s) => s.t % 1000 === 900)
    .map((s) => ({
      segundo: s.turn,
      objetivoRot: s.targetRotation,
      objetivoSway: s.targetSway,
      poseRot: s.jawRotation,
      poseSway: s.jawOffsetX,
    }));
  const targetChanges = perSecond.filter(
    (s, i) => i > 0 && (s.objetivoRot !== perSecond[i - 1].objetivoRot || s.objetivoSway !== perSecond[i - 1].objetivoSway),
  ).length;
  return { samples, perSecond, targetChanges };
}

const idleSeries = buildIdleSeries();

const out = {
  protocol: "silencio 0.3s / habla 1.5s (rms 0.2-0.5-0.8) / silencio 0.4s @60Hz",
  speech: {
    local: { ...sLocal, mean: Number(sLocal.mean.toFixed(2)) },
    backend: { ...sBackend, mean: Number(sBackend.mean.toFixed(2)) },
    localZeroCrossings: zeroCrossings(speechLocal),
    localMidCrossingsPerSecond: Number((midCrossings(speechLocal) / 1.5).toFixed(2)),
    localReturnsToNeutral: sLocal.zero,
    maxAbsJumpLocalVsBackend: Number(maxJump.toFixed(2)),
  },
  silence: {
    initialAllZero: localY.slice(0, speechStart).every((v) => v === 0),
    finalAllZero: silenceEnd.every((v) => v === 0),
  },
  idle: {
    protocol: "serie idle: 6 s, muestreo cada 100 ms, objetivo nuevo cada 1000 ms (silencio, rng sembrado)",
    targetChangesIn6s: idleSeries.targetChanges,
    perSecond: idleSeries.perSecond,
    samples: idleSeries.samples,
  },
};
console.log(JSON.stringify(out, null, 2));
// Tabla de jaw (habla, path local) + tabla idle por segundo, para el runner.
console.table([
  { metrica: "maxSubidaLocalPx", antes: -28, despues: Number(sLocal.min.toFixed(2)) },
  { metrica: "mediaLocalPx", antes: -10, despues: Number(sLocal.mean.toFixed(2)) },
  { metrica: "maxSubidaBackendPx", antes: -28, despues: Number(sBackend.min.toFixed(2)) },
]);
console.table(idleSeries.perSecond);
