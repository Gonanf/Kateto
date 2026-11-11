# Entrevista: evento de oficina con elenco Live2D

## Why

Hipotenusa ya tiene un overlay con avatar de recorte y una escena de juicio, pero no tiene un **evento
secuencial**: varios agentes entrando de a uno a un mismo cuarto, con una cámara fija, un entrevistador
que pregunta, y un veredicto. Tampoco existe una escena de oficina ni un pipeline que convierta ese
evento en un video reproducible. Eso es lo que falta para poder mostrar el sistema como pieza de
producto y no como demo suelta.

## What Changes

- Nueva escena `entrevista` servida por el overlay: fondo de oficina, capa de oclusión (escritorio en
  primer plano) y objetos animados, producidos por runs de OpenDesign.
- Nuevo elenco Live2D: un modelo Cubism por candidato, cargado desde disco, con lip sync por envolvente
  de audio y motions de idle.
- Nuevo orquestador de evento: guion declarativo con tiempos absolutos (entrada, sentarse, preguntas,
  respuesta, veredicto, salida) y una máquina de estados que lo ejecuta.
- Nuevo render de video: mezcla de audio en los tiempos del guion y captura de la página en un `mp4`
  1920x1080, con verificación por `ffprobe`.
- Sin cambios de comportamiento en `courtroom`, `discussion` ni en el overlay existente.

## Capabilities

### New Capabilities

- `interview-event`: secuencia del evento de entrevistas (orden de candidatos, preguntas, veredicto,
  cierre) independiente del dibujado.
- `office-scene`: composición visual del cuarto de entrevistas en capas, con objetos animados y puerta
  sincronizada con el estado del evento.
- `live2d-cast`: carga y animación de un modelo Live2D por candidato, con lip sync y degradación
  controlada cuando un modelo no está disponible.
- `event-render`: conversión del guion en audio mezclado y video final verificable.

### Modified Capabilities

_(ninguna: el overlay existente no cambia de comportamiento)_

## Impact

- `hipotenusa/plugins/visual_overlay/web/` — nueva página de escena y su driver de guion.
- `assets/live2d/` — modelos Cubism (no versionados, descargados por script).
- `assets/vendor/live2d/` — runtime PixiJS + pixi-live2d-display + Cubism Core, versionado.
- `scripts/` — generador de guion/audio y render de video.
- `docs/design-entrevista/` — artefactos HTML producidos por OpenDesign, como referencia visual.
- Dependencias: `piper` (TTS local), `ffmpeg`, `playwright` (ya instalados en el host). Sin servicios
  de red en runtime.
