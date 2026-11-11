---
title: El stream como producto
description: Arquitectura del producto de stream — actividades rotativas, motor de comedia por plantillas, y retorno verificable.
---

# El stream como producto

El producto no es un evento. El producto es el **stream**, que ocurre todos los días y cambia
de actividad: un día la entrevista de candidatos, otro Minecraft, otro Pokémon, otro
60 Segundos. La entrevista es **una actividad entre miles**, no el formato.

De ahí sale la primera regla de arquitectura: **pocos personajes, muchas actividades**. La
variedad la aporta la situación, no el elenco. Un elenco chico con actividades rotativas
produce más combinaciones que seis personajes atados cada uno a su único formato, y es más
barato de entrenar: una voz, muchos contextos.

## Regla del personaje

Un personaje no se define por un oficio ni por un chiste. Se define por **tres defectos y un
deseo**. El defecto es lo que no sabe hacer bajo presión; el deseo es lo que quiere y no
puede tener. Ninguno de los dos se nombra en pantalla: si el personaje dice "soy malo para
X", el chiste se muere. Se muestra.

Un personaje definido por su formato (el de seguridad, el de críticas) es un **formato con
cara**, no un personaje. Sirve para arrancar, pero no aguanta una rotación de actividades.

## Motor de comedia

La entrevista funciona porque el marco ya instaló la expectativa: en una entrevista de
trabajo se sabe cómo hay que comportarse, así que cualquier desvío es gracia sin setup. Ese
es el mecanismo general, y aplica a toda actividad: **el formato hace el setup, el personaje
hace el desvío**.

Lo que NO funciona es pedirle al modelo que sea gracioso. Con un modelo chico, sin reintentos
y con latencia real, eso produce texto plano.

### La frase se compila, no se improvisa

Tres capas separadas:

1. **Marco cómico** — lo elige una regla, no el modelo.
2. **Huecos semánticos** — el modelo llena campos cortos y acotados.
3. **Renderizador** — compone la frase con ritmo, largo y estilo fijos.

```json
{ "sujeto": "pato", "anomalia": "parpadeo", "nivel": "naranja", "verbo": "mintió" }
```

El sistema renderiza: *"Amenaza: parpadeo. Nivel: naranja. Nota: el pato mintió."*

La línea citable está garantizada por la sintaxis, no por la inspiración. Cada personaje
tiene su plantilla y su **banco de valores permitidos**: verbos, abstracciones, objetos. El
modelo elige del banco; no puede salirse del molde.

### Fallback con personaje

Sin reintentos, el fallback no puede ser un error. Tiene que ser una frase del personaje que
además sirva siempre: "Error de lectura. Culpa preliminar: el pato."

### Fallar con personalidad

El error tiene que ser del personaje, no del sistema. No "no entiendo": "el objeto rechaza
ser comprendido". Es un comportamiento medible, no una instrucción de estilo.

## Retorno: el mecanismo, no el carisma

La parasociabilidad no se construye en una sesión; se construye cuando alguien vuelve y el
personaje lo registra. Y la gente no vuelve por encanto: vuelve porque **quedó algo abierto**.

El mecanismo: al cerrar cada stream se abren casos con condición verificable y ventana
temporal. Al abrir el siguiente se cierran públicamente, con evidencia. Eso convierte el
stream en una serie y no en días sueltos.

### Profetizar el contenedor, no el contenido

Con actividades rotativas no se puede prometer "mañana el jugador muere por un tronco":
depende del juego. Se promete lo que existe en **cualquier** stream.

| Dominio | Ejemplo | Verificación |
|---|---|---|
| Chat | "antes del minuto 7, tres usuarios distintos escriben 'tostada'" | logs de chat |
| Usuarios | "al menos un usuario de hoy vuelve a escribir mañana" | ids + timestamps |
| Comandos | "`!pato` se usa antes del minuto 10" | logs del bot |
| Metadatos | "el título del próximo stream contiene 'latencia'" | título publicado |
| Modelo | "la primera salida del modelo tiene exactamente 6 palabras" | logs de generación |
| Operador | "el operador cambia de escena antes del minuto 5" | marcador público |

El más robusto es el **sello portable**: hoy se elige un token (una palabra, un número, un
emoji), y mañana ese token tiene que aparecer en algún lugar auditable, sea cual sea la
actividad.

### El juez es código

El modelo narra, no juzga. Si el modelo decide si la profecía se cumplió, la trampa es
inevitable y el público la huele.

```python
def check(profecia, logs):
    return len({m.user for m in logs
                if m.t < profecia.deadline and profecia.palabra in m.text.lower()}) >= profecia.min_usuarios
```

Después el modelo recibe solo el resultado y escribe el veredicto en menos de ocho palabras.

### Publicar antes

Cada profecía se guarda con id, fecha, texto exacto, condición, ventana y método de
verificación, y se muestra públicamente antes de que ocurra. Si se quiere integridad
máxima, se publica un hash y se revela al día siguiente.

### Duro y blando

| Tipo | Etiqueta | Verificación | Reinterpretación |
|---|---|---|---|
| Estricta | `#duro` | automática | prohibida |
| Blanda | `#mito` | narrativa | permitida, declarada |

Mover el arco después de tirar la flecha es lo que rompe la confianza. La ambigüedad
declarada, en cambio, se perdona.

## Korat en este sistema

Korat no hace que el modelo sea gracioso. Hace que los **valores de los huecos** sean del
personaje: qué verbos usa, qué abstracciones elegiría, cuáles no diría nunca.

Ese es un objetivo angosto y entrenable, y es exactamente lo que capturan los pares
`chosen`/`rejected` que salen de los votos propios.

Estado real: según la última verificación, el 2.9B marcado como entrenado era el modelo base
(mismo md5), y el checkpoint real dio 0/3 en ORPO v7. Korat sirve hoy para especificar el
objetivo del entrenamiento, no para contar con una voz usable.

## Lo que no está decidido

- Cuántos personajes sostiene el elenco antes de que se confundan entre sí.
- Si la rotación es fija (calendario) o la elige el personaje.
- Qué actividad entra primero además de la entrevista.
- Cómo se cierra un caso abierto cuando la actividad siguiente no tiene logs comparables.

## Dónde vive el trabajo

Las hipótesis de esta página están sembradas en Eureka v2 (store `.eureka-korat`, hito
`m-stream`) como `st-01` a `st-08`. El detalle de cada una, con su criterio de aceptación,
está en `config/hipotenusa-stream.local.json` del repo Corolario.

### El gate del hito

El hito `m-stream` mide una sola cosa, porque el resto se deriva: **latencia del turno con
la salida dentro de plantilla**. `score = 1 - min(latencia_p50_ms, 4000)/4000`, y solo cuenta
si `valid_pct >= 0.95`. Rápido pero fuera de plantilla no es una mejora.

### Medición de modelos (2026-11-03)

Cada candidato corre en su propio `llama-server`, con el mismo hardware y la misma vara:
flash-attn encendido, KV cuantizada `q8_0`, contexto 16384, `ubatch` 256, `batch` 1024,
`--reasoning-budget 0` y `response_format: json_object`. Medido en la RX 6500 XT / Iris Xe,
ambas de 4 GB.

| modelo | ctx que cargó | turnos válidos | p50 | score |
|---|---|---|---|---|
| LFM3-1.7B | 16384 | 100% | 1216 ms | **0.696** |
| Pollux-E2B | 16384 | 100% | 2364 ms | 0.409 |
| RWKV7-Hipotenusa | 16384 | 0% | 2074 ms | — |
| Castor-E4B | 16384 | 100% | 3393 ms | 0.152 |
| RWKV-v7-2.9B | 16384 | 0% | **256 ms** | — |

Tres cosas que salen de ahí.

El contexto no fue el límite: los cinco cargaron 16384 con KV cuantizada en una placa de
4 GB. El límite es la velocidad del turno.

RWKV es cinco veces más rápido que todo lo demás y no respeta la plantilla. Esa es la
pregunta del proyecto: si RWKV puede restringirse a la plantilla, gana por goleada. Si no,
el motor vive en un modelo chico de otra familia.

`json_object` no garantiza que los valores salgan del banco: con `ubatch` 512 apareció un
valor fuera de lista y el turno se cayó. La restricción tiene que ser una gramática, no una
instrucción.

### Lo que quedó abierto en la medición

El GBNF de varias reglas no parsea en este build de llama.cpp (`failed to parse grammar`),
aunque un `root ::= "a" | "b"` de una sola regla sí. Por eso los RWKV miden 0%: entran por
`/completion` y no se les puede imponer el esquema todavía. Arreglar eso, o meter un parser
tolerante del lado del renderizador, es lo primero que destraba el resto.
