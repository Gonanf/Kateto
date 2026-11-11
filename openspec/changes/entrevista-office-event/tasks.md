# Tasks — evento de entrevista

## 1. Arte (OpenDesign)

- [x] 1.1 Proyecto `entrevista-oficina` en el daemon y run de diseño con brief de tres capas
- [x] 1.2 Verificar los tres HTML en disco: ids `#bg-*` / `#fg-*`, 1920x1080, sin imágenes externas
- [x] 1.3 Capturas de los tres artefactos y revisión visual (fondo, primer plano, objetos)
- [x] 1.4 Copiar los artefactos a `hipotenusa/plugins/visual_overlay/web/entrevista/` y a `docs/design-entrevista/`

## 2. Elenco Live2D

- [x] 2.1 Bajar los modelos Cubism de muestra a `assets/live2d/` (`scripts/fetch_live2d_models.py`)
- [x] 2.2 Vendorizar PixiJS + pixi-live2d-display + Cubism Core en `assets/vendor/live2d/`
- [x] 2.3 Cargar un modelo por candidato y colocar el candidato detrás del escritorio
- [x] 2.4 Lip sync por envolvente precalculada sobre `ParamMouthOpenY`
- [x] 2.5 Degradación: marcador con el nombre si un modelo no carga

## 3. Escena

- [x] 3.1 Página `interview-event.html`: fondo, elenco, primer plano y HUD
- [x] 3.2 Puerta sincronizada con `enter` / `leave` (vano inyectado + bisagra)
- [x] 3.3 Placa de candidato, tarjeta de pregunta, subtítulos, veredicto con puntaje y slates
- [x] 3.4 Motor de cues por tiempo absoluto (sin timers encadenados)

## 4. Guion y audio

- [x] 4.1 `scripts/build_interview_event.py`: TTS por personaje, envolventes, guion con tiempos
- [x] 4.2 Mezcla continua en `assets/entrevista/mix.wav`
- [x] 4.3 Un único `hired` en el guion (verificado por el validador del build)

## 5. Video

- [x] 5.1 `scripts/render_interview_event.mjs`: captura 1920x1080 y muxeo con la mezcla
- [x] 5.2 Verificación por `ffprobe`: 1920x1080, pista de audio, duración contra el guion
- [x] 5.3 Entrega del mp4 al usuario

## 6. Integración con el runtime

- [x] 6.1 Ruta `/entrevista-event` y montaje `/media/` en el servidor del overlay
- [x] 6.2 `scripts/serve_scene.py` para correr la escena sin levantar el runtime completo
