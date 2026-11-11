#!/usr/bin/env node
/**
 * Graba el evento de entrevista y lo entrega como mp4.
 *
 *   node scripts/render_interview_event.mjs [--port 8791] [--out out/entrevista.mp4]
 *
 * Requiere el servidor de scripts/serve_scene.py escuchando en --port.
 * Captura la página a 1920x1080 con Playwright y muxea la pista de audio que generó
 * scripts/build_interview_event.py. Verifica el resultado con ffprobe.
 */
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

// playwright global: ESM no respeta NODE_PATH, así que lo resolvemos por require con fallback.
const require = createRequire(import.meta.url);
const { chromium } = (() => {
  for (const p of ['playwright', '/usr/lib/node_modules/playwright']) {
    try { return require(p); } catch { /* siguiente */ }
  }
  throw new Error('no encontré playwright: instalalo o exportá PLAYWRIGHT_PATH');
})();

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1]]);
  return acc;
}, []));
const PORT = Number(args.port || 8791);
const REPO = resolve(new URL('..', import.meta.url).pathname);
const OUT = resolve(REPO, args.out || 'out/entrevista.mp4');
const PAGE = `http://127.0.0.1:${PORT}/hipotenusa/plugins/visual_overlay/web/interview-event.html`;
const guion = JSON.parse(
  execFileSync('python3', ['-c', 'import json,sys;print(open(sys.argv[1]).read())',
    join(REPO, 'assets/entrevista/guion.json')]).toString());
const MIX = join(REPO, 'assets/entrevista/mix.wav');

const run = (cmd, argv) => execFileSync(cmd, argv, { stdio: ['ignore', 'pipe', 'pipe'] }).toString();

if (!existsSync(MIX)) throw new Error(`falta ${MIX}: corré scripts/build_interview_event.py primero`);

const work = mkdtempSync(join(tmpdir(), 'entrevista-'));
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/home/chaos/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome',
  args: ['--enable-unsafe-swiftshader', '--autoplay-policy=no-user-gesture-required',
    '--force-device-scale-factor=1', '--hide-scrollbars'],
});
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  recordVideo: { dir: work, size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));

await page.goto(PAGE, { waitUntil: 'load' });
await page.waitForFunction('window.__ready === true', null, { timeout: 180000 });
const fallbacks = await page.evaluate(() => document.querySelectorAll('.fallback').length);
console.log(`elenco listo · marcadores de fallback: ${fallbacks}`);

await page.evaluate(() => window.playEvent());
await page.waitForTimeout(Math.round((guion.duration + 1.6) * 1000));
const video = page.video();
await context.close();
await browser.close();

const webm = await video.path();
const webmDur = Number(run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration',
  '-of', 'default=nw=1:nk=1', webm]).trim());
console.log(`captura: ${webmDur.toFixed(2)}s (guion ${guion.duration}s)`);

// La captura arranca antes del evento. La página emite un frame blanco al arrancar:
// lo buscamos para recortar el pre-roll y que el audio caiga donde corresponde.
const stats = run('ffmpeg', ['-i', webm, '-t', '12', '-vf',
  'scale=64:36,signalstats,metadata=print:file=-', '-f', 'null', '-']);
const yavg = [...stats.matchAll(/lavfi\.signalstats\.YAVG=([\d.]+)/g)].map((m) => Number(m[1]));
if (!yavg.length) throw new Error('no pude leer los frames para sincronizar');
const peak = Math.max(...yavg);
if (peak < 200) throw new Error(`no encontré la marca de sincronización (YAVG máx ${peak})`);
const offset = (yavg.indexOf(peak) / 25).toFixed(3);
console.log(`pre-roll recortado: ${offset}s (YAVG ${peak.toFixed(0)})`);

run('ffmpeg', ['-y', '-loglevel', 'error', '-i', webm, '-i', MIX,
  '-filter_complex', `[0:v]trim=start=${offset},setpts=PTS-STARTPTS[v]`,
  '-map', '[v]', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'medium', '-crf', '19',
  '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', OUT]);

const probe = JSON.parse(run('ffprobe', ['-v', 'error', '-print_format', 'json',
  '-show_streams', '-show_format', OUT]));
const v = probe.streams.find((s) => s.codec_type === 'video');
const a = probe.streams.find((s) => s.codec_type === 'audio');
const dur = Number(probe.format.duration);
rmSync(work, { recursive: true, force: true });

if (!v || v.width !== 1920 || v.height !== 1080) throw new Error('el video no salió 1920x1080');
if (!a) throw new Error('el mp4 no tiene pista de audio');
if (Math.abs(dur - guion.duration) > 1.0) {
  throw new Error(`duración ${dur.toFixed(2)}s no coincide con el guion ${guion.duration}s`);
}
if (errors.length) console.log('errores de página:', JSON.stringify(errors.slice(0, 4)));
console.log(JSON.stringify({
  out: OUT, duration: Number(dur.toFixed(2)), size_mb: Number((statSync(OUT).size / 1e6).toFixed(1)),
  video: `${v.codec_name} ${v.width}x${v.height}`, audio: `${a.codec_name} ${a.sample_rate}Hz`,
  fallbacks,
}, null, 1));
