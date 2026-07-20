---
id: 17
title: "TUI: Switch de plugins no visible, voces deshabilitadas no aparecen en el tree"
severity: Media
status: resolved
resolved: 2026-07-20
component: kateto/plugins/system/tui.py / kateto/tests/test_tui.py / kateto/run_mode.py
---

## 17. TUI: Switch de plugins no visible, voces deshabilitadas no aparecen en el tree

**Severidad:** Media
**Componente:** `kateto/plugins/system/tui.py`, `kateto/tests/test_tui.py`, `kateto/run_mode.py`

### Descripción

Dos problemas de visibilidad en el TUI (modo real, sin `--fixture`):

1. **Plugin Switch ausente en la fila**: El `_plugin_row()` (tui.py:577) crea un `Switch` de Textual para togglear cada plugin, pero en terminales angostas el Switch queda fuera del ancho visible del panel. El usuario ve solo `⚪`, el nombre del plugin, y el texto de estado de audio — el Switch (que está en el DOM) se recorta por overflow del `Horizontal`.

2. **Voces deshabilitadas invisibles en el voice tree**: `workflow_voices` en `run_mode.py:277-280` filtra solo voces con `settings.enabled == True`. La `_populate_voice_tree()` (tui.py:620) itera sobre `workflow_voices`, así que voces deshabilitadas simplemente no aparecen en el árbol. No hay forma de verlas ni reactivarlas desde la UI.

### Impacto

- Los plugins no se pueden habilitar/deshabilitar desde el TUI porque el Switch no se ve (aunque el handler `on_switch_changed` funciona correctamente si se accede por código/test).
- Las voces deshabilitadas son invisibles en el panel de voces. El usuario no puede ver qué voces existen ni cuál es su estado, y no hay un control para habilitarlas desde la UI.

### Causa

**Para el Switch:**
- La fila del plugin usa un `Horizontal` con ancho `1fr` (todo el ancho del panel izquierdo que es `width: 40%`).
- Los hijos tienen anchos fijos: `Static(.plugin-status)` mide 3, `Button(.plugin-name)` mide 24, `Static(audio-status)` es auto, y el `Switch` no tiene ancho definido excepto `margin: 0 2`.
- En una terminal de ~80 columnas, el panel izquierdo mide ~32 caracteres. Con 3 + 24 + auto (~2-3) ya se usan ~29-30, dejando espacio insuficiente para que el Switch se renderice.
- El `Horizontal` de Textual no maneja overflow por defecto — los hijos que exceden se recortan.

**Para las voces:**
- `RuntimeOwner` construye `workflow_voices` solo con voces habilitadas del config (`run_mode.py:277-280`).
- El voice tree se puebla exclusivamente desde `workflow_voices` (`tui.py:623`).
- No hay fuente alternativa de datos que liste todas las voces conocidas (ej. del `VoiceProfile` en `factory.py`).

**Solución aplicada:**

1. El `Grid` de cada fila reserva una columna de seis celdas para el `Switch` real y el selector del plugin usa el espacio restante, con un ancho mínimo de una celda.
2. El `Switch` recibe una clase específica y margen cero para que su pista y control permanezcan dentro de la fila en terminales angostas.
3. Se agregó una prueba de regresión con terminal de 30 columnas que verifica la geometría renderizada del `Switch` y que el selector no colapse.
4. Se conserva la corrección previa que incluye las voces configuradas aunque estén deshabilitadas, permitiendo mostrarlas en el tree.

**Archivos modificados:** `kateto/plugins/system/tui.py`, `kateto/tests/test_tui.py`, `kateto/run_mode.py`

**Posible solución (original):**

1. Para el Switch:
   - Reducir el ancho del Button de 24 a algo menor, o usar `width: auto` con un max-width.
   - O aplicar `overflow-x: auto` al `.plugin-row`.
   - O usar un layout que se adapte mejor (ej. `GridLayout` con proporciones).

2. Para las voces:
   - Separar el concepto de "voces disponibles" (todas las configuradas en `config.toml` o conocidas por `factory.py`) de "voces habilitadas".
   - `workflow_voices` debería incluir todas las voces configuradas.
   - La rama del voice tree debería mostrar estado (enabled/disabled) con un icono y idealmente un Switch o botón para habilitar.
   - El fixture ya usa `workflow_voices = ("Jane", "Doktor", "Conquest")` (tui.py:54), hardcodeando las 3 — eso funciona para fixture pero no para modo real.
