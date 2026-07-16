import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { setTimeout as wait } from "node:timers/promises";
import { once } from "node:events";
import process from "node:process";
import playwright from "/home/chaos/node_modules/playwright/index.js";

const { chromium } = playwright;
const args = process.argv.slice(2);

function value(name, fallback = "") {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] ?? fallback : fallback;
}

function positiveInteger(name, fallback) {
  const parsed = Number(value(name, String(fallback)));
  if (!Number.isInteger(parsed) || parsed <= 0) throw new Error(`${name} must be a positive integer`);
  return parsed;
}

function resolveXtermAssets() {
  const requestedCdn = {
    script: "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.3.0/lib/xterm.js",
    stylesheet: "https://cdn.jsdelivr.net/npm/@xterm/xterm@5.3.0/css/xterm.css",
  };
  const cdn = {
    source: "cdn",
    version: "5.3.0",
    script: "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js",
    stylesheet: "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css",
    requestedCdn,
  };
  const configuredScript = process.env.XTERM_JS_PATH ? resolve(process.env.XTERM_JS_PATH) : null;
  const candidates = configuredScript
    ? [configuredScript]
    : [
        resolve(process.cwd(), "node_modules/@xterm/xterm/lib/xterm.js"),
        "/home/chaos/proyectos/hermes-agent/node_modules/@xterm/xterm/lib/xterm.js",
      ];
  const script = candidates.find((candidate) => existsSync(candidate));
  if (!script) return cdn;

  const root = dirname(dirname(script));
  const stylesheet = process.env.XTERM_CSS_PATH ? resolve(process.env.XTERM_CSS_PATH) : join(root, "css/xterm.css");
  if (!existsSync(stylesheet)) return cdn;

  const packagePath = join(root, "package.json");
  const version = existsSync(packagePath) ? JSON.parse(readFileSync(packagePath, "utf8")).version : "unknown";
  return { source: "local", script, stylesheet, version };
}

function childIsAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== "ESRCH";
  }
}

async function waitForClose(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) return true;
  return Promise.race([
    once(child, "close").then(() => true),
    wait(timeoutMs).then(() => false),
  ]);
}

async function captureCommand(command, input, columns, rows) {
  const terminalCommand = `stty rows ${rows} cols ${columns}; exec ${command}`;
  const child = spawn("script", ["-qfec", terminalCommand, "/dev/null"], {
    cwd: process.cwd(),
    env: { ...process.env, TERM: "xterm-256color" },
    stdio: ["pipe", "pipe", "pipe"],
  });
  const output = [];
  let childError = null;
  child.stdout.on("data", (chunk) => output.push(Buffer.from(chunk)));
  child.stderr.on("data", (chunk) => output.push(Buffer.from(chunk)));
  child.once("error", (error) => { childError = error; });

  await wait(1500);
  if (childError) throw childError;
  if (input.includes("{Enter}") && child.exitCode === null && !child.stdin.destroyed) child.stdin.write("\r\n");
  await wait(1200);
  if (child.exitCode === null && !child.stdin.destroyed) child.stdin.write("q");

  let childExited = await waitForClose(child, 6000);
  if (!childExited && child.exitCode === null) {
    child.kill("SIGTERM");
    childExited = await waitForClose(child, 1500);
  }
  if (childError) throw childError;

  return {
    output: Buffer.concat(output),
    cleanup: {
      childPid: child.pid ?? null,
      childExited,
      childExitCode: child.exitCode,
      childSignal: child.signalCode,
      childAliveAfterTeardown: childIsAlive(child.pid),
    },
  };
}

function pngDimensions(png) {
  if (png.length < 24 || png.toString("ascii", 1, 4) !== "PNG") throw new Error("Playwright did not return a PNG screenshot");
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

async function renderInXterm({ title, ansi, columns, rows, width, height, assets, screenshotPath }) {
  const alternateScreenLeave = "\x1b[?1049l";
  const alternateScreenLeaveOffset = ansi.lastIndexOf(alternateScreenLeave);
  const snapshot = {
    omittedAlternateScreenTeardown: alternateScreenLeaveOffset >= 0,
    alternateScreenLeaveOffset: alternateScreenLeaveOffset >= 0 ? alternateScreenLeaveOffset : null,
  };
  const snapshotAnsi = alternateScreenLeaveOffset >= 0 ? ansi.slice(0, alternateScreenLeaveOffset) : ansi;
  const browser = await chromium.launch({ headless: true });
  let browserClosed = false;
  try {
    const page = await browser.newPage({ viewport: { width, height } });
    const browserErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(`console:${message.text()}`);
    });
    page.on("pageerror", (error) => browserErrors.push(`pageerror:${error.message}`));

    await page.setContent("<style>html,body,#terminal{width:100%;height:100%;margin:0;overflow:hidden;background:#1e1e1e}</style><div id='terminal'></div>");
    await page.addStyleTag(assets.source === "cdn" ? { url: assets.stylesheet } : { path: assets.stylesheet });
    await page.addScriptTag(assets.source === "cdn" ? { url: assets.script } : { path: assets.script });
    await page.waitForFunction(() => typeof window.Terminal === "function");

    const rendering = await page.evaluate(async ({ documentTitle, output, terminalColumns, terminalRows, viewportWidth, viewportHeight }) => {
      document.title = documentTitle;
      const terminal = new window.Terminal({
        cols: terminalColumns,
        rows: terminalRows,
        cursorBlink: false,
        fontFamily: "DejaVu Sans Mono, monospace",
        fontSize: 14,
        lineHeight: 1.2,
        scrollback: 10_000,
        theme: { background: "#1e1e1e", foreground: "#e6e6e6" },
      });
      terminal.open(document.querySelector("#terminal"));
      await new Promise((complete) => terminal.write(output, complete));
      terminal.refresh(0, terminal.rows - 1);
      await new Promise((complete) => requestAnimationFrame(() => requestAnimationFrame(complete)));

      const surface = document.querySelector("#terminal .xterm");
      const rowsElement = document.querySelector("#terminal .xterm-rows");
      const naturalBox = surface?.getBoundingClientRect();
      const scale = naturalBox ? Math.min(1, viewportWidth / naturalBox.width, viewportHeight / naturalBox.height) : 1;
      if (surface && scale < 1) {
        surface.style.transformOrigin = "top left";
        surface.style.transform = `scale(${scale})`;
        await new Promise((complete) => requestAnimationFrame(complete));
      }
      const transcript = Array.from(
        { length: terminal.rows },
        (_, row) => terminal.buffer.active.getLine(terminal.buffer.active.baseY + row)?.translateToString(true) ?? "",
      ).join("\n") + "\n";
      const box = surface?.getBoundingClientRect();
      const result = {
        engine: "xterm.js",
        surface: {
          selector: "#terminal .xterm",
          present: Boolean(surface),
          hasRowsElement: Boolean(rowsElement),
          preElementCount: document.querySelectorAll("pre").length,
          classNames: Array.from(document.querySelectorAll("#terminal [class]"), (element) => element.className)
            .filter((className) => typeof className === "string" && className.startsWith("xterm")),
          naturalWidth: naturalBox?.width ?? 0,
          naturalHeight: naturalBox?.height ?? 0,
          scale,
          width: box?.width ?? 0,
          height: box?.height ?? 0,
        },
        terminal: { columns: terminal.cols, rows: terminal.rows },
        transcript,
      };
      if (!result.surface.present || !result.surface.hasRowsElement || result.surface.preElementCount !== 0) {
        throw new Error("xterm terminal surface or text layer was not rendered");
      }
      window.__katetoTerminal = terminal;
      return result;
    }, {
      documentTitle: title,
      output: snapshotAnsi,
      terminalColumns: columns,
      terminalRows: rows,
      viewportWidth: width,
      viewportHeight: height,
    });

    const screenshot = await page.screenshot({ path: screenshotPath, clip: { x: 0, y: 0, width, height } });
    await page.evaluate(() => window.__katetoTerminal?.dispose());
    if (browserErrors.length > 0) throw new Error(browserErrors.join("\n"));
    return { ...rendering, snapshot, screenshotDimensions: pngDimensions(screenshot) };
  } finally {
    await browser.close();
    browserClosed = true;
  }
}

const title = value("--title", "Terminal QA");
const command = value("--command");
const fromFile = value("--from-file");
const input = value("--input", "");
const evidenceDir = value("--evidence-dir", ".omo/evidence/terminal-qa");
const columns = positiveInteger("--cols", 100);
const rows = positiveInteger("--rows", 30);
const width = positiveInteger("--width", columns * 9);
const height = positiveInteger("--height", rows * 18);
mkdirSync(evidenceDir, { recursive: true });

let capture = null;
let rendering = null;
let assets = null;
let error = null;
try {
  if (Boolean(command) === Boolean(fromFile)) throw new Error("provide exactly one of --command or --from-file");
  assets = resolveXtermAssets();
  capture = fromFile
    ? { output: readFileSync(fromFile), cleanup: { childPid: null, childExited: true, childExitCode: null, childSignal: null, childAliveAfterTeardown: false } }
    : await captureCommand(command, input, columns, rows);
  const screenshotPath = join(evidenceDir, "terminal.png");
  rendering = await renderInXterm({
    title,
    ansi: capture.output.toString("utf8"),
    columns,
    rows,
    width,
    height,
    assets,
    screenshotPath,
  });
  copyFileSync(screenshotPath, join(evidenceDir, "terminal-screenshot.png"));
  writeFileSync(join(evidenceDir, "terminal-ansi.txt"), capture.output);
  writeFileSync(join(evidenceDir, "terminal.txt"), rendering.transcript, "utf8");
  writeFileSync(join(evidenceDir, "terminal-transcript.txt"), rendering.transcript, "utf8");
} catch (caught) {
  error = caught instanceof Error ? caught.message : String(caught);
  console.error(error);
}

const metadata = {
  title,
  command: command || null,
  fromFile: fromFile || null,
  input,
  requestedDimensions: { columns, rows, width, height },
  exitCode: capture?.cleanup.childExitCode ?? null,
  screenshot: rendering ? "terminal.png" : null,
  legacyScreenshot: rendering ? "terminal-screenshot.png" : null,
  transcript: rendering ? "terminal.txt" : null,
  ansi: capture ? "terminal-ansi.txt" : null,
  rendering: rendering && assets ? {
    engine: rendering.engine,
    assetSource: assets.source,
    version: assets.version,
    script: assets.script,
    stylesheet: assets.stylesheet,
    requestedCdn: assets.requestedCdn ?? null,
    surface: rendering.surface,
    terminal: rendering.terminal,
    snapshot: rendering.snapshot,
  } : null,
  screenshotDimensions: rendering?.screenshotDimensions ?? null,
  cleanup: {
    ...(capture?.cleanup ?? { childPid: null, childExited: false, childExitCode: null, childSignal: null, childAliveAfterTeardown: false }),
    browserClosed: Boolean(rendering),
  },
  error,
};
writeFileSync(join(evidenceDir, "metadata.json"), JSON.stringify(metadata, null, 2));

if (error || !rendering?.transcript.includes("PLUGINS / VOICES") || !rendering.transcript.includes("EVENT STREAM")) process.exitCode = 1;
