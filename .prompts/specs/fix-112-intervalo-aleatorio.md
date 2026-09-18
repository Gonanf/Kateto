# Visión periódica: el intervalo tiene que ser aleatorio dentro de un rango

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Pedido (usuario, textual)
"lo de vídeo rag debería ser aleatorio en un rango de tiempo"

## Estado actual
Hoy el intervalo es fijo: `vision_interval` (por voz, default `"30s"`) se registra como job INTERVAL en
el scheduler (con ack + reintento de fix-107) y dispara exacto cada 30 s. Eso se siente mecánico: la voz
comenta siempre con la misma cadencia.

## Fix esperado
1. **Rango configurable por voz**: `vision_interval_min` y `vision_interval_max` (p.ej. `20s` y `90s`),
   con `vision_interval` como compatibilidad (si no hay min/max, comportamiento actual exacto).
2. **Mecánica recomendada** (aprovecha el portón de imagen repetida de fix-111, que es barato):
   - el job del scheduler se registra con el intervalo **mínimo** (es la granularidad del tick);
   - en cada tick el plugin sortea un objetivo aleatorio en `[min, max]` (por fuente/voz) y **sólo narra**
     si además pasó el chequeo de imagen (no repetida) y ya se cumplió el objetivo sorteado;
   - después de narrar, vuelve a sortear. Así los comentarios caen en tiempos irregulares pero nunca más
     seguido que el mínimo ni más espaciado que el máximo.
   - Si el tick llega y la pantalla no cambió, no se gasta llamada al VLM (ya lo cubre fix-111).
3. **Aleatoriedad testeable**: la fuente del azar tiene que poder inyectarse (por ejemplo un
   `random.Random(seed)` o una callable en el plugin) para que el test sea determinista. Documentá el
   parámetro en el constructor.
4. **Validación de config**: si `min > max`, o alguno es <= 0, avisar claro (error al cargar o warning
   con el valor efectivo), no romper el arranque. Si sólo hay uno de los dos, el otro toma el mismo valor
   y el comportamiento es fijo.
5. **No rompas lo de fix-107**: sigue habiendo un solo job por voz, con ack del scheduler y reintento; el
   intervalo del job es el mínimo del rango. `disable()` cancela igual que ahora.
6. El log tiene que hacer visible el sorteo: p.ej. `[vision] next jane narration in 47s (range 20-90s)`.

## Tests (obligatorios)
- Con semilla fija y `min=20s max=90s`: la secuencia de esperas cae dentro del rango y **no** es constante.
- `min == max` ⇒ se comporta igual que antes (mismo intervalo fijo).
- Sólo `vision_interval` (sin min/max) ⇒ comportamiento actual, sin cambios.
- `min > max` ⇒ se avisa y no explota.
- El job se registra con el intervalo mínimo (assert sobre el `schedule_request` emitido).
- Los tests de fix-107 (ack, reintento, sin duplicados) y de fix-111 siguen verdes.

## Docs
- Bug/feature (id siguiente) "intervalo aleatorio dentro de un rango para la visión periódica".
- `plugins/vision.md` (documentar min/max, el sorteo y que el tick es el mínimo).

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or scheduler"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: la de la rama al momento de arrancar
   (compará contra los 3 fallos preexistentes: `test_audio_capture`, 2× `test_voice_history`)
3. `git diff --stat`
4. En el resumen: la lista de esperas sorteadas en el test (para mostrar el rango real).

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Usar `random` global sin poder sembrarlo
  (el test tiene que ser determinista).
