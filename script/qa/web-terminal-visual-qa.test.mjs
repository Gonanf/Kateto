import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "../..");
const harnessPath = join(scriptDirectory, "web-terminal-visual-qa.mjs");
const evidenceDirectory = resolve(
  process.env.HARNESS_EVIDENCE_DIR ?? join(repositoryRoot, ".omo/evidence/terminal-qa-test"),
);

function pngDimensions(path) {
  const png = readFileSync(path);
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

function runHarness(name, command, { columns = 40, rows = 8, width = 400, height = 160 } = {}, environment = {}) {
  const artifactDirectory = join(evidenceDirectory, name);
  mkdirSync(artifactDirectory, { recursive: true });
  const result = spawnSync(
    process.execPath,
    [
      harnessPath,
      "--title",
      "xterm regression",
      "--command",
      command,
      "--cols",
      String(columns),
      "--rows",
      String(rows),
      "--width",
      String(width),
      "--height",
      String(height),
      "--evidence-dir",
      artifactDirectory,
    ],
    { cwd: repositoryRoot, encoding: "utf8", env: { ...process.env, ...environment }, timeout: 30_000 },
  );
  assert.equal(result.error, undefined, result.stderr ?? "");
  assert.equal(result.status, 0, `${result.stdout ?? ""}\n${result.stderr ?? ""}`);
  return {
    artifactDirectory,
    metadata: JSON.parse(readFileSync(join(artifactDirectory, "metadata.json"), "utf8")),
  };
}

function assertRealXterm(metadata) {
  assert.equal(metadata.rendering.engine, "xterm.js");
  assert.equal(metadata.rendering.surface.selector, "#terminal .xterm");
  assert.equal(metadata.rendering.surface.preElementCount, 0);
  assert.equal(metadata.rendering.surface.hasRowsElement, true);
  assert.equal(metadata.cleanup.childExited, true);
  assert.equal(metadata.cleanup.browserClosed, true);
}

test("renders captured output through xterm at the requested dimensions", () => {
  const { artifactDirectory, metadata } = runHarness(
    "basic",
    "printf '\\033[38;2;10;200;100mPLUGINS / VOICES\\033[0m\\nEVENT STREAM\\n'",
  );

  assertRealXterm(metadata);
  assert.deepEqual(metadata.requestedDimensions, { columns: 40, rows: 8, width: 400, height: 160 });
  assert.deepEqual(pngDimensions(join(artifactDirectory, "terminal.png")), { width: 400, height: 160 });
  assert.deepEqual(pngDimensions(join(artifactDirectory, "terminal-screenshot.png")), { width: 400, height: 160 });
  assert.match(readFileSync(join(artifactDirectory, "terminal.txt"), "utf8"), /PLUGINS \/ VOICES/);
  assert.match(readFileSync(join(artifactDirectory, "terminal.txt"), "utf8"), /EVENT STREAM/);
});

test("captures the xterm alternate screen before its teardown restores the shell", () => {
  const { artifactDirectory, metadata } = runHarness(
    "alternate-screen",
    "printf '\\033[?1049h\\033[2J\\033[HPLUGINS / VOICES\\nEVENT STREAM\\n\\033[?1049lafter teardown\\n'",
  );

  assertRealXterm(metadata);
  assert.equal(metadata.rendering.snapshot.omittedAlternateScreenTeardown, true);
  const transcript = readFileSync(join(artifactDirectory, "terminal.txt"), "utf8");
  assert.match(transcript, /PLUGINS \/ VOICES/);
  assert.match(transcript, /EVENT STREAM/);
  assert.doesNotMatch(transcript, /after teardown/);
});

test("fits the live xterm surface inside the requested screenshot frame", () => {
  const dimensions = { columns: 100, rows: 30, width: 900, height: 540 };
  const { metadata } = runHarness(
    "frame-fit",
    "printf 'PLUGINS / VOICES\\nEVENT STREAM\\n'",
    dimensions,
  );

  assertRealXterm(metadata);
  assert.ok(metadata.rendering.surface.width <= dimensions.width);
  assert.ok(metadata.rendering.surface.height <= dimensions.height);
});

test("falls back to the pinned CDN xterm bundle when the configured local bundle is missing", () => {
  const { metadata } = runHarness(
    "cdn-fallback",
    "printf 'PLUGINS / VOICES\\nEVENT STREAM\\n'",
    undefined,
    { XTERM_JS_PATH: join(evidenceDirectory, "missing-xterm.js") },
  );

  assertRealXterm(metadata);
  assert.equal(metadata.rendering.assetSource, "cdn");
  assert.equal(metadata.rendering.version, "5.3.0");
  assert.equal(metadata.rendering.script, "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js");
  assert.equal(metadata.rendering.stylesheet, "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css");
  assert.equal(metadata.rendering.requestedCdn.script, "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.3.0/lib/xterm.js");
});
