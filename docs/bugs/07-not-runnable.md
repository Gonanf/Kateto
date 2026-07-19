---
id: 7
title: "Proyecto no runneable sin configuración externa"
severity: Alta
status: open
component: README.md, config/defaults/config.toml
---

## 7. Proyecto no runneable sin configuración externa

**Severidad:** Alta (para nuevos desarrolladores)
**Componente:** `README.md`, `config/defaults/config.toml`

El sistema requiere servidores externos funcionando (whisper.cpp, zonos.cpp, llama.cpp) y no hay:
- `docker-compose.yml` para levantar todo
- Scripts de setup automático
- Modo "offline" con modelos mock para desarrollo
- Validación temprana de conectividad al iniciar

**Impacto:** Un nuevo desarrollador no puede ejecutar `kateto live` sin primero configurar manualmente 3 servidores de inferencia. La fricción de onboarding es alta.

**Causa:** El MVP asume que el desarrollador ya tiene los servidores corriendo (entorno existente del creador). No se diseñó para portabilidad.

**Posible solución:**
1. Agregar `kateto doctor` que verifique conectividad con cada servidor
2. Agregar modo demo (sin servidores reales, respuestas sintéticas)
3. Documentar en README los comandos exactos para iniciar cada servidor
4. Docker compose como opción
