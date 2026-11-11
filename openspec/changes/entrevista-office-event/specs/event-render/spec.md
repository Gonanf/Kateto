## Purpose

Convierte el guion del evento en piezas verificables: un audio continuo con las líneas en sus tiempos y un
video `mp4` que muestra la escena real ejecutándose, con duración y pista de audio comprobadas.

## ADDED Requirements

### Requirement: Guion con tiempos absolutos

El render SHALL partir de un guion en JSON con el instante absoluto de cada línea y cada transición, y
SHALL derivar de ahí tanto el audio como la ejecución de la escena.

#### Scenario: Tiempos consistentes

- **WHEN** se genera el audio mezclado y se ejecuta la escena
- **THEN** ambos usan los mismos instantes absolutos y ninguna línea aparece corrida respecto del guion.

### Requirement: Pista de audio mezclada

El render SHALL producir una única pista de audio continua, con una voz distinta por personaje y silencio
en los tramos sin diálogo.

#### Scenario: Mezcla completa

- **WHEN** el guion tiene N líneas de diálogo
- **THEN** la pista mezclada dura lo que dura el evento y contiene las N líneas en sus instantes.

### Requirement: Video final verificable

El render SHALL entregar un `mp4` H.264 con audio AAC, 1920x1080, y SHALL verificar el archivo con
`ffprobe` antes de darlo por bueno.

#### Scenario: Verificación del archivo

- **WHEN** el render termina
- **THEN** `ffprobe` reporta un stream de video 1920x1080 y un stream de audio, y la duración del video
  coincide con la del guion con tolerancia de un segundo.

#### Scenario: Fallo de captura

- **WHEN** la captura no produce frames
- **THEN** el render falla con un mensaje que nombra el paso fallido y no deja un `mp4` vacío como
  entregable.
