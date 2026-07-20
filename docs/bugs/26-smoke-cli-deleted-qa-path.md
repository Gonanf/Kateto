---
id: 26
title: "CLI smoke apunta a scripts/qa eliminado"
severity: Media
status: open
component: kateto/__main__.py / script/qa
---

## 26. CLI smoke apunta a scripts/qa eliminado

**Severidad:** Media
**Componente:** `kateto/__main__.py`, `script/qa`

### Descripción

`uv run kateto smoke --fixture` intenta ejecutar `scripts/qa/acceptance.py`, pero el árbol vigente conserva únicamente `script/qa/web-terminal-visual-qa.*`. El comando documentado como smoke de publicación termina con `FileNotFoundError` antes de ejecutar la validación.

### Impacto

El camino de preflight para jueces y el plan de publicación no pueden demostrar un smoke bounded mediante el entrypoint declarado.

### Causa

La documentación y el entrypoint conservan rutas de la estructura anterior (`scripts/qa`), mientras que el árbol fue limpiado a la estructura singular `script/qa` y el acceptance runner ya no está presente.

### Posible solución

1. Restaurar o reemplazar el runner con un smoke interno mantenido bajo `script/qa`.
2. Actualizar `kateto/__main__.py`, README y tests para usar una única ruta.
3. Ejecutar el smoke en configuración temporal y registrar evidencia antes de publicar.
