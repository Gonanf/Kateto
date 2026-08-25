---
title: "Voz falla en generate: list_events revienta con anotaciones UnionType"
description: "53. Voz falla en generate: list_events revienta con anotaciones UnionType"
---


## 53. Voz falla en generate: list_events revienta con anotaciones UnionType

**Severidad:** Alta
**Componente:** `kateto/voices/tools.py`

### Descripción

Durante el manejo del evento `generate`, la herramienta `list_events` (`VoiceToolExecutor._list_events`) lanza `AttributeError: 'types.UnionType' object has no attribute '__name__'` cuando un contrato de evento tiene campos anotados con uniones (`str | None`). El error aislado se emite como evento de error:

```
{"plugin":"doktor","event_name":"generate","error_type":"AttributeError","message":"'types.UnionType' object has no attribute '__name__'"}
```

### Impacto

La voz (p.ej. Doktor) no puede completar una generación que requiera inspeccionar los eventos disponibles: la llamada a la herramienta falla, el resultado queda en error y el agente pierde la iteración. La mayoría de los contratos en `core/event.py` usan `str | None` (p.ej. `GenerateData.prompt`), por lo que el crash es reproducible con cualquier evento registrado.

### Causa

`field_info.annotation.__name__` accede directamente a `__name__`, pero en Python 3.12 una anotación `str | None` resuelve a `types.UnionType`, que no expone `__name__`. La misma función ya usaba el patrón seguro `getattr(annotation, "__name__", str(annotation))` en `build_event_tools`, pero `_list_events` quedó con el acceso directo.

### Solución aplicada

Se reemplazó el acceso directo por el patrón `getattr` ya establecido en el archivo:

```python
"type": getattr(field_info.annotation, "__name__", str(field_info.annotation))
if field_info.annotation
else "unknown",
```

Regresión cubierta por `kateto/tests/test_list_events_union_type.py`, que registra un contrato con campos `str | None` y verifica que `list_events` los renderiza (`"str | None"`) en lugar de lanzar.

**Archivos:** `kateto/voices/tools.py`, `kateto/tests/test_list_events_union_type.py`
