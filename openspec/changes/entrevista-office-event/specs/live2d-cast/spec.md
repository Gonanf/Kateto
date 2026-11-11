## Purpose

Carga y anima el elenco Live2D del evento: un modelo Cubism por candidato, colocado en la silla, con la boca
movida por el audio de su línea y una pose de espera cuando no habla.

## ADDED Requirements

### Requirement: Un modelo por candidato

El elenco SHALL cargar un modelo Live2D distinto por candidato, desde archivos locales, y SHALL mostrar
como máximo un candidato animado en escena por vez.

#### Scenario: Carga local sin red

- **WHEN** la escena arranca con el guion de cuatro candidatos
- **THEN** los cuatro modelos quedan cargados desde rutas locales `assets/live2d/` y ninguna request de red
  pide el `.moc3` ni las texturas.

#### Scenario: Un solo candidato animado

- **WHEN** el evento está en `interviewing`
- **THEN** sólo el modelo del candidato vigente está actualizándose; los demás están fuera del lienzo.

### Requirement: Lip sync por audio de la línea

El modelo del candidato SHALL abrir la boca en proporción a la envolvente de la línea de audio que está
sonando y SHALL volver a boca cerrada al terminar la línea.

#### Scenario: Boca cerrada en silencio

- **WHEN** no hay línea de audio activa
- **THEN** el parámetro de apertura de boca del candidato vale 0 en menos de 200 ms.

#### Scenario: Boca sigue la voz

- **WHEN** una línea del candidato tiene energía audible
- **THEN** el parámetro de apertura de boca varía con la envolvente de esa línea y no queda fijo en un
  valor distinto de cero.

### Requirement: Pose de espera y expresión de entrada

El modelo SHALL tener una animación de espera mientras escucha y SHALL aplicar una expresión propia al
entrar a la sala.

#### Scenario: Expresión al entrar

- **WHEN** el candidato cruza la puerta
- **THEN** su modelo aplica una expresión declarada en el guion y arranca la animación de espera.

### Requirement: Degradación sin abortar el evento

Si un modelo no carga, la escena SHALL mostrar un marcador con el nombre del candidato y SHALL continuar el
evento hasta el slate final.

#### Scenario: Modelo roto

- **WHEN** el archivo de un candidato falla al cargar
- **THEN** la escena muestra su nombre en un marcador visible, registra el error en consola y el evento
  llega a `done`.
