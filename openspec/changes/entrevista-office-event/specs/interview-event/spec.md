## Purpose

Orquesta el evento de entrevistas como una secuencia de estados observable: qué candidato entra, qué se
le pregunta, qué contesta y con qué veredicto sale. No sabe dibujar: sólo declara el orden y las
condiciones para que la escena y el render lo ejecuten.

## ADDED Requirements

### Requirement: Orden de candidatos

El evento SHALL procesar a los candidatos uno por uno, en el orden declarado por el guion, sin que dos
candidatos ocupen la sala al mismo tiempo.

#### Scenario: Entrada y salida de un candidato

- **WHEN** el guion declara los candidatos `[conquest, jane, whisperer, rice]`
- **THEN** el evento emite `candidate_enter`, preguntas, respuestas y `candidate_leave` de cada uno en ese
  orden, y no emite el `candidate_enter` siguiente antes del `candidate_leave` anterior.

#### Scenario: Un candidato por vez en escena

- **WHEN** el estado del evento es `interviewing`
- **THEN** hay exactamente un candidato visible en la escena.

### Requirement: Preguntas y respuestas

El evento SHALL publicar la pregunta vigente antes de la respuesta y SHALL mantenerla visible mientras el
candidato habla.

#### Scenario: Pregunta visible durante la respuesta

- **WHEN** empieza una línea de respuesta del candidato
- **THEN** la tarjeta de pregunta muestra el texto de la pregunta que la originó y no se limpia hasta que
  la respuesta termina.

### Requirement: Veredicto por candidato

El evento SHALL emitir un veredicto por cada candidato, con puntaje entero de 0 a 100 y resultado
`hired` o `rejected`, y SHALL declarar un único `hired` en todo el evento.

#### Scenario: Un solo contratado

- **WHEN** el evento termina
- **THEN** la suma de veredictos `hired` es exactamente 1 y cada candidato tiene su puntaje entre 0 y 100.

#### Scenario: El veredicto sigue a la última respuesta

- **WHEN** termina la última línea de respuesta de un candidato
- **THEN** el veredicto de ese candidato se emite antes de su `candidate_leave`.

### Requirement: Cierre del evento

El evento SHALL cerrar con un slate final que nombre al candidato contratado y SHALL marcar el estado
`done` al terminar.

#### Scenario: Slate final

- **WHEN** el último candidato sale de la sala
- **THEN** se muestra el slate de cierre con el nombre del contratado y el estado pasa a `done`.
