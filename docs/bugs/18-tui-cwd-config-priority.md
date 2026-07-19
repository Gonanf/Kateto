---
id: 18
title: "TUI usa Path.cwd() como config_dir, ignorando el user config y reactivando duplicados"
severity: Crítica
status: resolved
resolved: 2026-07-19
component: kateto/plugins/system/tui.py / kateto/__main__.py
---

## 18. TUI usa `Path.cwd()` como config_dir, ignorando el user config y reactivando duplicados

**Severidad:** Crítica
**Componente:** `kateto/plugins/system/tui.py` (línea 834), `kateto/__main__.py` (línea 39)

### Descripción

Cuando se ejecuta `kateto tui` desde la raíz del proyecto, `run_tui()` resuelve `config_dir` a `Path.cwd()` (la raíz del proyecto) en lugar de la ubicación estándar del user config (`~/.config/kateto/`). Esto hace que el TUI cargue y opere sobre archivos en la raíz del proyecto, ignorando por completo el user config real.

**Esto revive los duplicados que el bug #13 había eliminado.** La raíz tiene ahora:

| Archivo/Directorio | Propósito real | Pero el TUI lo usa como... |
|---|---|---|
| `config.toml` (raíz) | Archivo de workspace, posiblemente creado durante debugging | Config principal del runtime |
| `skills/` (raíz) | Caché de skills — recreada por workaround del bug #17 | Directorio de skills del runtime |
| `voices/` (raíz) | Workspace/dev | Directorio de voces del runtime |

### Causa raíz

**`run_tui()` en `tui.py:834`:**
```python
resolved_config_dir = (Path.cwd() if config_dir is None else config_dir).resolve()
```

Cuando `kateto tui` se invoca sin `--config-dir` (que no existe como flag), `config_dir` es `None` y cae a `Path.cwd()`.

**Todos los demás entrypoints** usan `resolve_config_dir()` → `~/.config/kateto/`:

| Entrypoint | Cómo resuelve config_dir |
|---|---|
| `kateto config check` | `load_config()` sin args → `resolve_config_dir()` |
| `kateto run` | `load_config()` sin args → `resolve_config_dir()` |
| `kateto tui` | `Path.cwd()` — **inconsistente** |

### Impacto

- **Las skills en la raíz del proyecto prevalecen** sobre las de `~/.config/kateto/skills/`. Si difieren, el usuario recibe behaviour inesperado.
- **El `config.toml` de raíz** puede tener settings distintos (diferente modelo LLM, voces deshabilitadas, device de micrófono distinto). El usuario configura `~/.config/kateto/config.toml` pero el TUI usa el de raíz.
- **`voices/` en raíz** usada como base para assets de voz (reference.wav, etc). Si no existe, crashea o falla silenciosamente.
- **Confusión de desarrollo**: se edita `~/.config/kateto/config.toml`, se ejecuta `kateto tui`, y los cambios no tienen efecto.
- **El bug #13 se revierte de facto**: los directorios eliminados vuelven a ser necesarios para el TUI.

### Solución aplicada

Opción A: `run_tui()` ahora usa `resolve_config_dir()` en lugar de `Path.cwd()` como fallback cuando no se pasa `config_dir`. Esto alinea el TUI con `kateto run` y `kateto config check`.

**Archivo modificado:** `kateto/plugins/system/tui.py` (línea 833)

### Posible solución (alternativa)

Opción A (mínima, recomendada): Cambiar `run_tui()` para usar `resolve_config_dir()` por defecto, igual que los demás entrypoints:

```python
# En tui.py, importar resolve_config_dir
from kateto.core.config import load_config, resolve_config_dir

def run_tui(*, fixture: bool = False, config_dir: Path | None = None) -> None:
    resolved_config_dir = (resolve_config_dir() if config_dir is None else config_dir).resolve()
    ...
```

Opción B (más explícita): Agregar flag `--config-dir` a `kateto tui` y pasar el valor.

Opción C (documentación): Agregar advertencia en `run_tui()` de que usa CWD.

**Archivos a modificar:** `kateto/plugins/system/tui.py` (línea 834)
