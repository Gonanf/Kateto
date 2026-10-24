# Cordis: el paradigma, no la libreria

## 0. Veredicto

Cordis formaliza un paradigma riguroso de composabilidad espaciotemporal que ataca directamente dos debilidades estructurales observadas en Kateto: la falta de reversibilidad local de efectos colaterales (donde la inicialización y el desmantelamiento ocurren en métodos asimétricos y desconectados, provocando fugas de suscripciones y configuraciones) y la ausencia de resolución reactiva de coefectos (donde las dependencias entre plugins se reducen a un mero filtrado de eventos en el momento del despacho en lugar de gobernar el estado de activación del componente). No obstante, la adopción de Cordis como librería de software queda descartada: Cordis está desarrollado en TypeScript sobre Node/Yarn en un ecosistema ajeno al stack de Kateto (Python 3.12+), su API pública es declarada explícitamente inestable por sus propios autores, y el harness de Kateto consume únicamente un ~0,64% del tiempo total del turno conversacional, haciendo que una reescritura carezca por completo de justificación de rendimiento. Por lo tanto, el veredicto es concluyente: **se adopta la disciplina conceptual del paradigma (efectos revertibles con acumuladores de disposers LIFO y coefectos reactivos para activación de servicios), pero se rechaza la importación de la dependencia y la reescritura de código en TypeScript**.

| Decision | Cambia? | Evidencia |
|---|---|---|
| Ciclo de vida asimétrico (`enable`/`disable` desconectados) | Cambia | `kateto/core/plugin.py:81`, `kateto/core/manager.py:94` |
| Estado efímero de turno acumulado en la instancia del Plugin | Cambia | `kateto/core/plugin.py:35`, `kateto/core/plugin.py:204` |
| Dependencias como filtro de despacho mudo vs reactividad | Cambia | `kateto/core/manager.py:353`, `kateto/core/manager.py:375` |
| Registros globales sin función inversa de desinscripción | Cambia | `kateto/core/plugin.py:24`, `kateto/core/manager.py:70` |
| Lenguaje y runtime del harness (Python vs TypeScript) | No cambia | `pyproject.toml`, medición de harness (~0,64% del turno) |
| Bus de eventos tipados desacoplados (`EventModel`) | No cambia | `kateto/core/manager.py:61`, `kateto/core/manager.py:185` |
| Separación de prompt de voz (`stable_prompt` vs `volatile_block`) | No cambia | `kateto/voices/context.py:70`, `kateto/voices/context.py:129` |

## 1. Que es Cordis y por que no se importa

Cordis es un meta-framework de extensibilidad y orquestación desarrollado en TypeScript (`https://github.com/cordiverse/cordis`, con más de 9.000 estrellas en GitHub), respaldado teóricamente por el paper *A Programming Paradigm for Spatiotemporal Composability* (arXiv 2608.25512). Su tesis central postula que los sistemas modulares modernos requieren resolver dos dimensiones ortogonales: la **composabilidad temporal** (la capacidad de revertir completamente cualquier efecto colateral originado por un componente al ser desactivado o recargado) y la **composabilidad espacial** (la capacidad de declarar, verificar y reaccionar ante las dependencias que existen entre componentes heterogéneos). Para resolver ambas dimensiones sin fragmentar el sistema, Cordis unifica el contexto de efectos y el contexto de coefectos en una única estructura mediadora de ejecución.

Una de las críticas más lúcidas del paper a arquitecturas previas (específicamente la API de extensiones de VSCode, en §1.2.1) subraya que exigir un método `deactivate` separado de `activate` *"separa la disposición del efecto de su creación, violando la localidad de la preocupación y haciendo difícil de verificar la limpieza completa"*. En el código actual de Kateto encontramos exactamente este mismo síntoma: la clase base `Plugin` expone `enable()` y `disable()` como métodos desacoplados (`kateto/core/plugin.py:81`), lo que traslada al autor del plugin la carga mental de recordar cada recurso adquirido, listener suscripto o subproceso lanzado, abriendo la puerta a fugas de memoria y desincronizaciones cuando la desactivación no replica simétricamente la inversa de la inicialización.

A pesar de la elegancia teórica de este modelo, **Cordis no se importa como dependencia por tres razones arquitectónicas insalvables**:
1. **Incompatibilidad de stack y costo de reescritura:** Kateto está construido íntegramente sobre Python 3.12+, `asyncio` y Pydantic. Adoptar la librería Cordis implicaría reescribir el harness en TypeScript o incurrir en un puente entre procesos (IPC) para orquestar extensiones. Mediciones reales en el repositorio demuestran que el harness de Kateto consume apenas el ~0,64% del tiempo total del turno (el restante 99,36% se concentra en la latencia de inferencia de LLM y síntesis TTS/ASR), por lo que cualquier ganancia hipotética en TypeScript es irrelevante frente al costo de reescritura.
2. **Inestabilidad manifiesta del upstream:** El propio archivo README oficial del repositorio Cordis declara textualmente: *"Cordis is under active development. The API is not yet stable and may change without notice."* Construir la infraestructura nuclear de Kateto sobre una biblioteca externa con breaking changes no planificados introduciría un riesgo inaceptable.
3. **El principio de adopción paradigmática:** Los principios del cálculo formal (efectos revertibles, acumulador LIFO de disposers, coefectos reactivos) son patrones matemáticos de diseño independientes del lenguaje de programación. Se debe incorporar el paradigma directamente en el motor de `PluginManager` de Python, sin arrastrar dependencias foráneas ni capas superfluas.

## 2. Los mecanismos, en una linea cada uno

- **Efectos revertibles (composabilidad temporal):** Toda mutación sobre el contexto registra inmediatamente su propia función inversa (`disposer`), acumulada por componente en una pila LIFO para garantizar un desmantelamiento simétrico y completo ante descargas o fallos.
- **Coefectos reactivos (composabilidad espacial):** Cada componente declara explícitamente los servicios que consume (`inject`), permitiendo que el runtime lo transicione reactivamente entre estados activo e inactivo según la presencia o ausencia de dichas dependencias en el entorno.
- **Contexto único y mediador unificado:** Un único contenedor central canaliza de manera coherente tanto los efectos publicados como los coefectos requeridos por las entidades, administrando ámbitos aislados para componentes y turnos.
- **Confluencia e intercalación sin interferencias:** La mediación canónica del contexto garantiza la confluencia en el entrelazado de efectos de plugins independientes, evitando colisiones en el estado global sin necesidad de bloqueos manuales.
- **Disposer por inscripción y localidad de ciclo de vida:** La creación del recurso y su procedimiento de liberación coexisten en el mismo bloque sintáctico (`ctx.effect`), erradicando la deslocalización entre activación y desactivación.

## 3. Mapeo contra lo que ya tenemos

| Concepto Cordis | Equivalente aca | Evidencia archivo:linea | Falta |
|---|---|---|---|
| `ctx.effect(callback)` / Acumulador LIFO de disposers | Hooks `enable()` y `disable()` | `kateto/core/plugin.py:81`, `kateto/core/manager.py:94` | Localidad de limpieza; no hay pila LIFO automática de disposers por componente. |
| `fiber.inject` / Coefectos reactivos y cálculo de ciclo de vida | `capabilities` y `depts` | `kateto/core/plugin.py:35`, `kateto/core/manager.py:353` | Transición reactiva de estado (`INACTIVE`/`ACTIVE`); hoy solo operan como filtros de enrutamiento al emitir. |
| Contexto hijo (`fiber.ctx`) y resolución de servicios | `DiscoveryContext.get_shared` y `manager` | `kateto/core/discovery.py:24`, `kateto/core/discovery.py:32` | Jerarquía dinámica y aislamiento reactivo; es un diccionario mutable ad-hoc sin ciclo de vida. |
| Eventos tipados con modos declarados (`emit`, `waterfall`, `bail`) | `PluginManager.emit` con `EventModel` | `kateto/core/manager.py:61`, `kateto/core/manager.py:185` | Modos de intercepción tipo middleware (`waterfall`) o corte anticipado (`bail`); solo hay broadcast asíncrono. |
| Aislamiento e intercepción (`ctx.isolate`, `ctx.intercept`) | Anti-spoofing por departamentos `_validate_dept` | `kateto/core/manager.py:375` | Espacios de nombres aislados para servicios y sobreescritura de handlers sin colisiones de nombres. |
| Supervisión de subprocesos / Sidecars | Tareas asyncio en Plugin y lanzamiento de sidecars | `kateto/core/plugin.py:163`, `kateto/core/plugin.py:167` | Vinculación del ciclo de vida del subproceso con el plugin consumidor; no hay disposer local ni supervisión activa. |

## 4. Decisiones que cambian

### Decisión 1: Sustitución de hooks asimétricos `enable`/`disable` por registro de efectos revertibles con disposers LIFO

**Veredicto:** Cambia

- **HOY:** `Plugin.enable` y `Plugin.disable` son métodos independientes sin estado compartido garantizado (`kateto/core/plugin.py:81`). En `PluginManager.disable_plugin`, se invoca `plugin.disable()` de manera desligada de lo que hizo `enable()` (`kateto/core/manager.py:94`), provocando que cualquier recurso no liberado manualmente quede huérfano.
- **CAMBIA A:** Introducir el método `ctx.effect(handler)` o generador asíncrono en el ciclo de vida del plugin. Todo recurso asignado, subproceso iniciado o listener inscripto debe ceder o registrar su propio `disposer`. Al desactivar el plugin, `PluginManager` debe ejecutar todos los disposers registrados en estricto orden LIFO.
- **CÓMO SE VERIFICA:** Test unitario en pytest donde un plugin de prueba adquiere tres recursos simulados mediante `ctx.effect()`. Al forzar un error en el tercer registro o llamar a `disable_plugin`, comprobar mediante aserciones de secuencia que los disposers 2 y 1 fueron invocados exactamente en orden inverso (LIFO) y el estado global quedó restaurado.
- **COSTO:** Toca `kateto/core/plugin.py` y `kateto/core/manager.py`. Migración no disruptiva: se preservan `enable`/`disable` heredados por retrocompatibilidad mientras se promueve el nuevo protocolo de efectos.
- **¿toca el camino crítico?:** No (afecta la fase de ciclo de vida, arranque, detención y hot reload).

### Decisión 2: Desacoplamiento del estado mutable del turno conversacional fuera de la instancia duradera de `Plugin`

**Veredicto:** Cambia

- **HOY:** Las colas y acumuladores de eventos efímeros del turno conversacional residen directamente en atributos mutables de la instancia del plugin: `self.queue`, `self._batch_events` y `self._current_envelope` (`kateto/core/plugin.py:35`, `:56`). En `Plugin._run`, los eventos se acumulan hasta `batch_trigger` (`kateto/core/plugin.py:204`). Cuando ocurre un corte de turno por `on_interrupt` en `VoiceAgent` (símbolo `VoiceAgent.on_interrupt` en `kateto/voices/base.py`), se cancela la tarea pero la cola y `_batch_events` no se purgan, dejando residuos que contaminan turnos subsiguientes.
- **CAMBIA A:** Encapsular el estado volátil de cada turno en un objeto acotado (`TurnContext`) generado por turno. El buffer de acumulación debe crearse y destruirse junto con el turno; cualquier señal de `interrupt` debe descartar el `TurnContext` activo mediante su propio disposer sin dejar rastro en la instancia del `Plugin`.
- **CÓMO SE VERIFICA:** Test asíncrono que envíe eventos de texto parciales a un `VoiceAgent`, dispare un evento `interrupt` antes de que se emita `generate`, y verifique que el siguiente evento `generate` no incluye fragmentos del turno anterior interrumpido.
- **COSTO:** Modificación en `kateto/core/plugin.py`, `kateto/voices/base.py` y `kateto/voices/context.py:129`. Migración moderada.
- **¿toca el camino crítico?:** Sí (interviene directamente en el pipeline de procesamiento de eventos en tiempo real).

### Decisión 3: Coefectos reactivos para gobernanza de activación en lugar de filtrado estático en el despacho

**Veredicto:** Cambia

- **HOY:** Las capacidades requeridas y ofrecidas (`capabilities`, `depts`) se declaran como tuplas pasivas en el constructor del plugin (`kateto/core/plugin.py:35`) y se emplean exclusivamente como filtro de coincidencia al momento de despachar eventos en `PluginManager._resolve_subscribers` (`kateto/core/manager.py:353`) y `_validate_dept` (`kateto/core/manager.py:375`). Si un servicio indispensable no está disponible, el plugin permanece en estado habilitado pero silencioso o falla en tiempo de ejecución.
- **CAMBIA A:** Declarar formalmente los requerimientos de servicios como coefectos (`inject = ("tts", "transcription")`). El `PluginManager` debe mantener al componente en estado inactivo (`INACTIVE` / `⊥`) mientras sus coefectos no estén presentes en el registro, y transicionarlo reactivamente a `ACTIVE` en cuanto el proveedor del servicio sea registrado.
- **CÓMO SE VERIFICA:** Test de integración donde un plugin que declara `inject = ("llm_provider",)` se registra con el proveedor ausente. Verificar que su estado reportado sea inactivo y no reciba eventos. Al registrar dinámicamente un plugin que provea `llm_provider`, verificar que el consumidor pasa automáticamente a estado activo.
- **COSTO:** Toca `kateto/core/plugin.py`, `kateto/core/manager.py` y `kateto/core/discovery.py:24`. Migración baja.
- **¿toca el camino crítico?:** No (opera durante el registro y cambios de topología de plugins).

### Decisión 4: Reversibilidad garantizada en registros de configuración y observadores

**Veredicto:** Cambia

- **HOY:** Los métodos `register_config_param` y `register_voice_param` escriben de forma irreversible en variables globales de módulo sin opción de desregistro (`kateto/core/plugin.py:24`, `:30`). Igualmente, `register_plugin` agrega el objeto a `self._registered` permanentemente (`kateto/core/manager.py:70`), y `disable_plugin` no remueve al plugin del diccionario (`kateto/core/manager.py:94`), persistiendo residuos durante recargas en caliente (`kateto/core/hot_reload.py:91`, `:104`).
- **CAMBIA A:** Asociar toda inscripción de configuración, observadores (`add_event_observer` en `kateto/core/manager.py:152`) y metadatos a la fibra del plugin llamador. Al deshabilitar o descargar un componente en `_refresh` (`kateto/core/hot_reload.py:104`), el manager debe purgar simétricamente todas sus entradas registradas.
- **CÓMO SE VERIFICA:** Test de recarga en caliente que verifique que tras registrar un plugin con parámetros y desactivarlo con `disable_plugin` o recargarlo con `_purge_plugins`, los registros de configuración y observadores vuelven exactamente al estado previo.
- **COSTO:** Modificación en `kateto/core/plugin.py`, `kateto/core/manager.py:70`, `kateto/core/manager.py:152` y `kateto/core/hot_reload.py:104`.
- **¿toca el camino crítico?:** No.

## 5. Decisiones que no cambian

- **No importar la librería Cordis ni reescribir Kateto en TypeScript:** Se mantiene la base de código 100% en Python 3.12+ (`pyproject.toml`). Kateto es un sistema de interacción por voz donde la latencia crítica reside en la inferencia acústica y del modelo de lenguaje, no en el microsegundo de despacho del harness (~0,64% del turno medido en perfiles de ejecución). La inestabilidad de la API de Cordis y la fricción de mantenimiento de un runtime bilingüe superan ampliamente cualquier beneficio cosmético.
- **No reemplazar el bus de eventos tipados por un contenedor de Inyección de Dependencias monolítico:** Kateto se rige por eventos asíncronos desacoplados modelados con Pydantic (`EventModel`, `kateto/core/event.py:8`). Este modelo es superior para pipelines de streaming multimedia que un contenedor DI tradicional centrado en llamadas a métodos RPC sincronizados.
- **No alterar la arquitectura de caché de prefijos estables del prompt:** La división entre `stable_prompt` y `volatile_block` (`kateto/voices/context.py:70`, `kateto/voices/context.py:129`) garantiza el ahorro de cómputo por reutilización de KV-cache en los motores de inferencia LLM. Esta optimización es completamente ortogonal a la composabilidad de plugins y debe conservarse intacta.

## 6. Regla de diseno para AGENTS.md

1. Tratá toda mutación de estado, suscripción a eventos o adquisición de recursos como un efecto colateral estrictamente revertible: cada registro debe asociar su propio disposer que el runtime ejecutará en orden LIFO al desactivar o recargar el componente.
2. Prohibido desacoplar la creación de la destrucción de recursos en métodos independientes sin tracking; la lógica de limpieza debe declararse en el mismo ámbito sintáctico donde se origina el recurso.
3. No almacenes estado mutable del turno conversacional en la instancia duradera del plugin; aislá los buffers efímeros en un contexto acotado al ciclo de vida del turno que se resetee automáticamente ante cualquier interrupción.
4. Declará las dependencias de servicios de manera explícita como coefectos; ningún plugin debe ejecutar lógica activa si sus dependencias obligatorias no están provistas y activas en el runtime.
5. El ciclo de vida de los subprocesos y sidecars debe pertenecer a la fibra del componente que los requiere, asegurando su supervisión continua y su apagado determinista cuando el componente es retirado.

## 7. Lo que NO verifique

- **Limitaciones formales del cálculo admitidas por el paper (arXiv 2608.25512):**
  - El propio paper admite explícitamente en §5.1.1 que el runtime no verifica formalmente la correctitud de las inversas: la función `disposer` es una responsabilidad exclusiva del programador y no existe comprobación automática de que realmente devuelva el sistema al estado pristino.
  - El testigo del coefecto (la propiedad de que operaciones concurrentes sobre la misma clave de servicio conmuten de forma segura) tampoco es verificado por el runtime en tiempo de ejecución.
  - La equivalencia observacional y las garantías de confluencia dependen de que los componentes no compartan memoria mutable por fuera del contexto unificado.
- **Alcance empírico no evaluado en este pase:**
  - No se examinó el código fuente TypeScript completo del monorepo `cordiverse/cordis` (más de 15 paquetes internos), centrándose la extracción en la especificación formal del paper (tabla 2, p.58) y el manual de referencia oficial.
  - No se ejecutaron pruebas de estrés de latencia en vivo bajo condiciones de alta concurrencia de audio ni conmutaciones masivas de modelos de lenguaje locales.
- **Resultado de la validación de hipótesis del orquestador:**
  - **H1 (Efectos sin inversa en registros globales):** CONFIRMADA. Se verificó que `register_config_param` y `register_voice_param` en `kateto/core/plugin.py:24`, `:30` no poseen mecanismo de desregistro, y `PluginManager.register_plugin` (`kateto/core/manager.py:70`) no es revertido por `disable_plugin` (`kateto/core/manager.py:94`).
  - **H2 (Dependencias como filtro de despacho pasivo):** CONFIRMADA. Se constató que `capabilities` y `depts` únicamente filtran suscriptores en `_resolve_subscribers` (`kateto/core/manager.py:353`) y `_validate_dept` (`kateto/core/manager.py:375`), sin inducir estados de inactividad reactiva en ausencia de dependencias.
  - **H3 (Sidecars como procesos huérfanos sin supervisión):** CONFIRMADA. En `supervisor.py` de hipotenusa (función `run(profile)` en la ruta de rama secundaria `/run/media/chaos/secundario/harness-wt/t_66196364-a/kateto/hipotenusa/supervisor.py`), los subprocesos se lanzan o adoptan al arrancar pero no son vigilados durante la ejecución ni vinculados a los plugins que los consumen.
  - **H4 (Estado por turno acoplado a la instancia del plugin):** CONFIRMADA. Se comprobó que `_batch_events` y `queue` residen en `kateto/core/plugin.py:56` y `kateto/core/plugin.py:204`, y la rutina `on_interrupt` en `VoiceAgent` (`kateto/voices/base.py`) no purga estos buffers, permitiendo que residuos de turnos abortados pervivan entre ejecuciones. Matiz: `on_interrupt` si renueva las colas del pipeline de audio (`pipeline.token_queue` y `pipeline.pcm_queue`), pero deja intactas las del plugin, que son las que alimentan el batch.
