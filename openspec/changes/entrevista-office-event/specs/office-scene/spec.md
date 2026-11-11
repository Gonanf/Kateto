## Purpose

Define la composición visual del cuarto de entrevistas: qué capas existen, cómo se apilan y qué objetos se
animan solos. La escena es un fondo de oficina con oclusión en primer plano, de modo que un personaje 2D
pueda quedar sentado detrás del escritorio.

## ADDED Requirements

### Requirement: Capas de la escena

La escena SHALL componerse de tres capas apiladas —fondo, elenco y primer plano— sobre un lienzo de
1920x1080 sin scroll ni bordes visibles.

#### Scenario: El escritorio ocluye al candidato

- **WHEN** un candidato está sentado en la silla
- **THEN** el borde del escritorio de la capa de primer plano se dibuja por encima de la parte inferior del
  personaje.

#### Scenario: Lienzo fijo

- **WHEN** la escena se abre en un viewport de 1920x1080
- **THEN** no aparece barra de scroll y el fondo cubre todo el viewport.

### Requirement: Puerta sincronizada

La capa de fondo SHALL exponer una puerta que se abre al entrar y salir un candidato y vuelve a cerrarse
cuando el candidato deja de cruzar el umbral.

#### Scenario: Apertura en la entrada

- **WHEN** el evento emite `candidate_enter`
- **THEN** la puerta pasa a abierta antes de que el personaje aparezca en el vano y se cierra después de
  que lo cruza.

### Requirement: Objetos animados en loop

La escena SHALL animar de forma continua el segundero del reloj, el vapor de la taza y el movimiento de la
planta, sin interrumpirse ni reiniciarse entre candidatos.

#### Scenario: Animación continua

- **WHEN** el evento pasa de un candidato al siguiente
- **THEN** el segundero del reloj conserva la fase que tenía y no vuelve a cero.

### Requirement: Procedencia del arte

Los fondos y objetos animados SHALL provenir de artefactos HTML producidos por runs del daemon de
OpenDesign y SHALL estar verificados en disco antes de integrarse.

#### Scenario: Artefacto verificado

- **WHEN** se integra el fondo de la oficina
- **THEN** existe en el repo el HTML producido por el run con los ids de capa documentados y una captura
  de pantalla del mismo archivo.
