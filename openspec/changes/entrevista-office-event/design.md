# Design — evento de entrevista con elenco Live2D

## Context

- El overlay actual (`index.html`) dibuja un avatar de recorte por CSS/JS y corre con audio PCM en el
  navegador. `courtroom.html` muestra varios personajes en zonas fijas con imágenes PNG.
- Ninguno de los dos tiene nociones de **tiempo absoluto**: son reactivos a eventos.
- El host tiene `piper` (4 voces es_*) con ONNX local, `ffmpeg` y Playwright con Chromium y WebGL por
  swiftshader. La sesión de video se puede capturar sin GPU real.
- Ver proposal.md — Why.

## Goals / Non-Goals

- Goal: una página que se ejecute sola y dure lo que diga el guion, sin servidor de runtime ni eventos.
- Goal: arte (fondo, primer plano, objetos) producido por OpenDesign y usado tal cual, no re-dibujado a mano.
- Goal: video final verificable por `ffprobe`.
- Non-goal: reemplazar el overlay reactivo ni integrar LLM/TTS en vivo. El guion es estático a propósito:
  la pieza a mostrar es la **integración visual**, no la latencia del runtime.

## Decisions

1. **Guion como fuente única de tiempo.** `assets/entrevista/guion.json` tiene eventos con `t` absoluto
   (segundos). El audio mezclado y el reloj de la página se derivan del mismo archivo, así no hay deriva.
   Alternativa descartada: encadenar `await audio.ended` — acumula drift y hace imposible mezclar antes.
2. **Lip sync por envolvente precalculada.** El generador mide RMS de cada WAV a 40 ms y lo guarda en el
   guion; el render interpola ese vector sobre `ParamMouthOpenY`. Alternativa descartada: `AnalyserNode`,
   que depende de que el navegador reproduzca audio y rompe la captura headless.
3. **Tres capas con iframes para el arte de OpenDesign.** Fondo y primer plano son HTML autónomos del
   daemon; se embeben sin reescribirlos y el elenco Live2D va en un canvas entre ambos. Alternativa
   descartada: extraer SVG del HTML — pierde el JS de animación de los objetos.
4. **Un canvas PixiJS con un modelo por candidato, montado al entrar y desmontado al salir.** Mantener los
   cuatro vivos cuesta memoria de texturas (Teto solo son 21 MB de PNG) sin ganancia visible.
5. **Captura por Playwright `recordVideo`** a 1920x1080 con reloj real, y mezcla de audio en paralelo con
   los tiempos del guion. Alternativa descartada: screenshots por frame (3.000 capturas, ~15 min).

## Risks / Trade-offs

- `recordVideo` graba a 25 fps y usa el reloj real: si la máquina se traba, el video se estira. Se verifica
  la duración contra el guion y se re-renderiza si difiere más de 1 s.
- Los modelos de muestra (CubismWebSamples) no se versionan: 50 MB. Se bajan con
  `scripts/fetch_live2d_models.py`; sin ellos la escena muestra marcadores con nombre.
- El modelo de Teto es VTube Studio, sin motions de idle: la pose de espera se arma con parámetros
  (respiración y parpadeo) en vez de un `.motion3.json`.

## Migration

Ninguna: página y assets nuevos, sin tocar el runtime existente.
