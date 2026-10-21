/**
 * Mask viseme bridge — teléfono (pantalla únicamente).
 *
 * Recibe mensajes `viseme` (contrato en kateto/core/event.py::VisemeData) y
 * anima el avatar a 60 fps con interpolación exponencial attack/release.
 * Sin dependencias ni DOM propio: el avatar se inyecta.
 *
 * Flujo: player._send_viseme → evento `viseme` → (WS /ws/mask, MASK-2) →
 * mask.html (MASK-1) → createVisemeAnimator(avatar).
 */

export const ATTACK_MS = 30; // subida de mandíbula (rápida)
export const RELEASE_MS = 120; // bajada (con inercia)
export const TARGET_FPS = 60;

const POSE_KEYS = ["jawOffsetX", "jawOffsetY", "jawRotation", "headOffsetY"];

function num(v) {
  return Number(v) || 0;
}

export function isVisemeMessage(msg) {
  return msg?.type === "viseme";
}

export function applyVisemeMessage(avatar, msg) {
  if (!isVisemeMessage(msg)) return false;
  if (typeof avatar?.setJawTransform !== "function") return false;
  avatar.setJawTransform({
    jawOffsetX: num(msg.jawOffsetX),
    jawOffsetY: num(msg.jawOffsetY),
    jawRotation: num(msg.jawRotation),
    headOffsetY: num(msg.headOffsetY),
  });
  return true;
}

export function createVisemeAnimator(avatar, options = {}) {
  const defaultNow =
    typeof performance !== "undefined" && typeof performance.now === "function"
      ? () => performance.now()
      : () => Date.now();
  const now = options.now || defaultNow;
  const requestFrame =
    options.requestFrame ||
    (typeof requestAnimationFrame === "function" ? requestAnimationFrame : null);
  const cancelFrame =
    options.cancelFrame ||
    (typeof cancelAnimationFrame === "function" ? cancelAnimationFrame : null);
  const fps = options.fps || TARGET_FPS;
  const intervalMs = 1000 / fps;

  const stats = {
    frames: 0,
    pushes: 0,
    renders: 0,
    lastPushMs: null,
    lastRenderMs: null,
    firstRenderLatencyMs: null,
  };

  const current = { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0, headOffsetY: 0 };
  const target = { jawOffsetX: 0, jawOffsetY: 0, jawRotation: 0, headOffsetY: 0 };

  let running = false;
  let frameHandle = null;
  let lastTickMs = null;
  let hasRendered = false;
  let latencyPending = false;

  const disabled = typeof avatar?.setJawTransform !== "function";

  function render(t) {
    stats.frames += 1;
    const dt = hasRendered
      ? Math.min(Math.max(t - lastTickMs, 0), 100)
      : stats.lastPushMs !== null
        ? Math.max(t - stats.lastPushMs, 0)
        : intervalMs;
    lastTickMs = t;
    hasRendered = true;
    for (const key of POSE_KEYS) {
      const tau = Math.abs(target[key]) > Math.abs(current[key]) ? ATTACK_MS : RELEASE_MS;
      const alpha = 1 - Math.exp(-dt / tau);
      current[key] += alpha * (target[key] - current[key]);
    }
    avatar.setJawTransform({
      jawOffsetX: current.jawOffsetX,
      jawOffsetY: current.jawOffsetY,
      jawRotation: current.jawRotation,
      headOffsetY: current.headOffsetY,
    });
    if (typeof avatar.setEyeOffset === "function") {
      avatar.setEyeOffset({ y: current.headOffsetY / 2.6 });
    }
    stats.renders += 1;
    stats.lastRenderMs = t;
    if (latencyPending) {
      const latency = t - (stats.lastPushMs ?? t);
      if (Number.isFinite(latency) && latency >= 0 && latency <= 1000) {
        stats.firstRenderLatencyMs = latency;
        latencyPending = false;
      }
    }
  }

  function tick(t) {
    frameHandle = null;
    if (!running) return;
    const time = typeof t === "number" ? t : now();
    if (hasRendered && time - lastTickMs < intervalMs) {
      frameHandle = requestFrame ? requestFrame(tick) : null;
      return;
    }
    render(time);
    frameHandle = requestFrame ? requestFrame(tick) : null;
  }

  function start() {
    if (disabled || running) return;
    running = true;
    hasRendered = false;
    lastTickMs = null;
    frameHandle = requestFrame ? requestFrame(tick) : null;
  }

  function stop() {
    running = false;
    if (frameHandle !== null && cancelFrame) {
      cancelFrame(frameHandle);
    }
    frameHandle = null;
  }

  function push(msg) {
    if (disabled || !isVisemeMessage(msg)) return false;
    target.jawOffsetX = num(msg.jawOffsetX);
    target.jawOffsetY = num(msg.jawOffsetY);
    target.jawRotation = num(msg.jawRotation);
    target.headOffsetY = num(msg.headOffsetY);
    stats.pushes += 1;
    stats.lastPushMs = now();
    latencyPending = true;
    return true;
  }

  return {
    push,
    start,
    stop,
    get stats() {
      return stats;
    },
    get current() {
      return { ...current };
    },
  };
}
