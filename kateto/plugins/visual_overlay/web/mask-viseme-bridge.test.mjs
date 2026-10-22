// Tests del mask-viseme-bridge (contrato `viseme` → avatar a 60 fps).
// node --test mask-viseme-bridge.test.mjs — sin dependencias ni DOM.
import { describe, it, test } from "node:test";
import assert from "node:assert/strict";

const mod = await import("./mask-viseme-bridge.js");
const { isVisemeMessage, applyVisemeMessage, createVisemeAnimator } = mod;

// Harness con reloj y frames inyectados: `advance(ms)` corre UN frame.
function makeHarness(startMs = 0) {
  let t = startMs;
  let cb = null;
  let handle = 0;
  const cancelled = [];
  const requestFrame = (fn) => {
    cb = fn;
    handle += 1;
    return handle;
  };
  const cancelFrame = (h) => {
    cancelled.push(h);
  };
  const advance = (ms) => {
    t += ms;
    const fn = cb;
    cb = null;
    if (fn) fn(t);
  };
  return { now: () => t, requestFrame, cancelFrame, advance, cancelled };
}

function makeAvatar(extra = {}) {
  const calls = [];
  return {
    calls,
    eyeCalls: [],
    setJawTransform(pose) {
      calls.push(pose);
    },
    setEyeOffset(pose) {
      this.eyeCalls.push(pose);
    },
    ...extra,
  };
}

describe("mask-viseme-bridge", () => {
  it("1. isVisemeMessage solo true para type:viseme", () => {
    assert.equal(isVisemeMessage({ type: "viseme" }), true);
    assert.equal(isVisemeMessage({ type: "subtitle" }), false);
    assert.equal(isVisemeMessage({}), false);
    assert.equal(isVisemeMessage(null), false);
  });

  it("2. applyVisemeMessage aplica los 4 campos y devuelve true", () => {
    const avatar = makeAvatar();
    const ok = applyVisemeMessage(avatar, {
      type: "viseme",
      jawOffsetX: 1,
      jawOffsetY: -2,
      jawRotation: 3,
      headOffsetY: 4,
    });
    assert.equal(ok, true);
    assert.equal(avatar.calls.length, 1);
    assert.deepEqual(avatar.calls[0], {
      jawOffsetX: 1,
      jawOffsetY: -2,
      jawRotation: 3,
      headOffsetY: 4,
    });
  });

  it("3. applyVisemeMessage con type:subtitle no toca el stub", () => {
    const avatar = makeAvatar();
    const ok = applyVisemeMessage(avatar, { type: "subtitle", text: "hola" });
    assert.equal(ok, false);
    assert.equal(avatar.calls.length, 0);
  });

  it("4. applyVisemeMessage sin setJawTransform no explota", () => {
    const avatar = {};
    assert.equal(applyVisemeMessage(avatar, { type: "viseme", jawOffsetY: -5 }), false);
  });

  it("5. interpola: intermedio en el primer frame y converge a -40", () => {
    const h = makeHarness(0);
    const avatar = makeAvatar();
    const anim = createVisemeAnimator(avatar, h);
    anim.start();
    assert.equal(anim.push({ type: "viseme", jawOffsetX: 0, jawOffsetY: -40, jawRotation: 0, headOffsetY: 0 }), true);
    h.advance(16);
    const first = avatar.calls.at(-1).jawOffsetY;
    assert.ok(first < 0 && first > -40, `primer frame intermedio, obtuvo ${first}`);
    for (let i = 0; i < 5; i++) h.advance(16);
    const finalY = avatar.calls.at(-1).jawOffsetY;
    assert.ok(Math.abs(finalY - -40) < 5, `converge cerca de -40, obtuvo ${finalY}`);
    anim.stop();
  });

  it("6. firstRenderLatencyMs <= 50 con frames de 16ms", () => {
    const h = makeHarness(0);
    const avatar = makeAvatar();
    const anim = createVisemeAnimator(avatar, h);
    anim.start();
    anim.push({ type: "viseme", jawOffsetY: -40 });
    h.advance(16);
    assert.ok(anim.stats.firstRenderLatencyMs !== null);
    assert.ok(anim.stats.firstRenderLatencyMs <= 50, `latencia ${anim.stats.firstRenderLatencyMs}`);
    anim.stop();
  });

  it("7. push no-viseme devuelve false y no incrementa pushes", () => {
    const h = makeHarness(0);
    const avatar = makeAvatar();
    const anim = createVisemeAnimator(avatar, h);
    anim.start();
    const before = anim.stats.pushes;
    assert.equal(anim.push({ type: "subtitle" }), false);
    assert.equal(anim.stats.pushes, before);
    anim.stop();
  });

  it("8. setEyeOffset se deriva de headOffsetY; sin él no explota", () => {
    const h = makeHarness(0);
    const withEyes = makeAvatar();
    const animEyes = createVisemeAnimator(withEyes, h);
    animEyes.start();
    animEyes.push({ type: "viseme", headOffsetY: 10 });
    h.advance(16);
    assert.ok(withEyes.eyeCalls.length >= 1);
    const renderedHead = withEyes.calls.at(-1).headOffsetY;
    assert.ok(Math.abs(withEyes.eyeCalls.at(-1).y - renderedHead / 2.6) < 0.01);
    animEyes.stop();

    const h2 = makeHarness(0);
    const noEyes = { setJawTransform() {} };
    const animNo = createVisemeAnimator(noEyes, h2);
    animNo.start();
    animNo.push({ type: "viseme", headOffsetY: 10 });
    h2.advance(16);
    animNo.stop();
  });

  it("9. start() es idempotente y stop() deja de pedir frames", () => {
    const h = makeHarness(0);
    const avatar = makeAvatar();
    const anim = createVisemeAnimator(avatar, h);
    anim.start();
    anim.start();
    // una sola programación inicial
    assert.equal(avatar.calls.length, 0);
    anim.stop();
    assert.ok(h.cancelled.length >= 1);
    const callsBefore = avatar.calls.length;
    h.advance(16);
    assert.equal(avatar.calls.length, callsBefore);
  });

  it("10. null/undefined se sanéan a 0", () => {
    const avatar = makeAvatar();
    assert.equal(
      applyVisemeMessage(avatar, {
        type: "viseme",
        jawOffsetX: null,
        jawOffsetY: undefined,
        jawRotation: null,
        headOffsetY: null,
      }),
      true,
    );
    assert.deepEqual(avatar.calls[0], {
      jawOffsetX: 0,
      jawOffsetY: 0,
      jawRotation: 0,
      headOffsetY: 0,
    });
  });
});

test("reloj por defecto = performance.now() (no mezcla con Date.now)", () => {
  const calls = [];
  const avatar = { setJawTransform: (pose) => calls.push(pose) };
  let pendingCb = null;
  const animator = createVisemeAnimator(avatar, {
    requestFrame: (cb) => { pendingCb = cb; return 1; },
    cancelFrame: () => {},
  });
  const t0 = performance.now();
  animator.start();
  animator.push({ type: "viseme", jawOffsetY: -40 });
  pendingCb(t0 + 16);
  assert.ok(animator.stats.firstRenderLatencyMs !== null);
  assert.ok(animator.stats.firstRenderLatencyMs >= 0);
  assert.ok(animator.stats.firstRenderLatencyMs <= 50);
  animator.stop();
});

