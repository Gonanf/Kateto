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
const { computeJawKinematics, computeBackendKinematics } = await import(modPath);

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

const out = {
  protocol: "silencio 0.3s / habla 1.5s (rms 0.2-0.5-0.8) / silencio 0.4s @60Hz",
  speech: {
    local: { ...sLocal, mean: Number(sLocal.mean.toFixed(2)) },
    backend: { ...sBackend, mean: Number(sBackend.mean.toFixed(2)) },
    localZeroCrossings: zeroCrossings(speechLocal),
    localReturnsToNeutral: sLocal.zero,
    maxAbsJumpLocalVsBackend: Number(maxJump.toFixed(2)),
  },
  silence: {
    initialAllZero: localY.slice(0, speechStart).every((v) => v === 0),
    finalAllZero: silenceEnd.every((v) => v === 0),
  },
};
console.log(JSON.stringify(out, null, 2));
