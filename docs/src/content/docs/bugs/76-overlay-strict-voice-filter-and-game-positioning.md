---
id: 76
title: "Visual overlay: filtrado estricto por ventana y posicionamiento programático para juegos (Chess/Versus/Sides)"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/
resolved: 2026-08-31
---

## 76. Visual overlay: filtrado estricto por ventana y posicionamiento programático para juegos (Chess/Versus/Sides)

**Severidad:** Media  
**Componente:** [`kateto/plugins/visual_overlay/`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/visual_overlay/) (`web/index.html`, `visual_overlay_plugin.py`, `core/event.py`)

### Descripción

1. **Sincronización no deseada entre ventanas:** Al abrir dos ventanas independientes con filtros diferentes (e.g. Ventana 1 con `?voices=jane` y Ventana 2 con `?voices=doktor`), cuando un agente hablaba, la lógica dinámica incondicionalmente añadía el agente a la lista activa de la otra ventana, provocando que ambas ventanas mostraran a todos los agentes juntos.
2. **Falta de posicionamiento programático para juegos:** Se requería la capacidad de colocar a dos o más agentes en lados opuestos de la pantalla (e.g. en un tablero de ajedrez, debates cara a cara, cartas, juegos por turnos) tanto desde la URL como dinámicamente mediante eventos desde scripts Python o plugins.

### Causa

- En `index.html`, la función `onSpeakerActivity` contenía `if (!agent && vid) { activeVoiceList.push(vid); renderAgentCards(...) }` sin verificar si la ventana tenía un filtro explícito en `currentVoices`.
- La disposición CSS era puramente relativa en fila inferior (`row`), sin soporte de anclajes laterales (`left`, `right`, `top`, `bottom`, `corners`) ni recepción de eventos de posición.

### Solución aplicada

1. **Filtrado estricto (`hasVoiceFilter`):**
   - Si la URL incluye `?voices=jane`, la ventana ignora categóricamente eventos y audio de cualquier otra voz que no esté en la lista permitida. Las ventanas dedicadas a avatares específicos nunca se contaminan ni sincronizan indeseadamente.
2. **Posicionamiento programático y Presets para Juegos:**
   - **Presets integrados:**
     - `layout=sides` / `layout=chess` / `layout=versus`: Coloca a los jugadores en lados opuestos de la pantalla (e.g. Jugador 1 a la izquierda, Jugador 2 a la derecha), con animación suave por CSS.
     - `layout=top-bottom`: Jugador superior e inferior.
     - `layout=corners`: 4 esquinas de la pantalla.
     - `layout=row`: Fila inferior centrada (por defecto).
     - `layout=single`: Solo el orador activo centrado.
   - **Parámetros URL:**
     - `?layout=sides&voices=jane,doktor`
     - `?pos_jane=left&pos_doktor=right`
     - `?pos_jane=10%,50%&pos_doktor=90%,50%`
   - **Control dinámico en tiempo real vía WebSocket:**
     - Se añadió el contrato [`OverlayLayout`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/core/event.py) en Kateto (`layout`, `positions`, `voices`).
     - Al emitir `overlay_layout` en el bus de Kateto, el overlay traslada y anima suavemente los avatares a las nuevas coordenadas.

**Archivos:** `kateto/plugins/visual_overlay/web/index.html`, `kateto/plugins/visual_overlay/visual_overlay_plugin.py`, `kateto/core/event.py`, `kateto/tests/test_visual_overlay.py`
