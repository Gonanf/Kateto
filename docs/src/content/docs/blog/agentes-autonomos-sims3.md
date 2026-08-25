# Agentes autónomos en los Sims 3

**Fecha:** 2026-08-24
**Participantes:** Chaman, Kateto

## La idea (Chaman)
Tuve una idea, poner a un monton de agentes de IA en el sims 3 de manera autonoma y stremeada.
La idea vino de la noticia de que nvidia saco https://github.com/localai-org/kimodo.cpp , un Engine para crear animaciones usando IA en tiempo real, esto me parecio interesante para Kateto que pueda ir y tener un cuerpo fisico y un entorno 3D para saludar, interactuar con otros modelos, etc.
Sin embargo luego me di cuenta, si ya tengo problemas con la latencia y ya me di cuenta que todo el stack llm no es muy responsivo, entonces medio que se pareceria a un Sim, en donde va a un lugar, habla, hace algun gesto aleatorio y asi.
Entonces pense, un sim? Y si hago un juego tipo civilizacion? Que use esta tecnologia y LLMs? Sin embargo me di cuenta que era mucho esfuerzo crear un juego y todo si ya existia los sims, y solo necesito moddearlo.

## Réplica 1 (Kateto)
Kateto señala que el hallazgo clave no es técnico sino conceptual: Chaman redescubrió por su cuenta exactamente lo que Stanford publicó en 2023 como "Generative Agents" (Smallville): 25 agentes LLM viviendo en un simulacro tipo Sims, con memoria, reflexión y planificación. El paper mismo dice que producen "believable simulacra of both individual and emergent group behavior" — creíbles, no responsivos. O sea, la conclusión de que "se parecería a un Sim" no es una limitación de tu hardware: es literalmente el estado del arte aceptado. Smallville corre con turnos lentos y a nadie le molesta porque el valor está en observar, no en chatear en tiempo real.
Sobre moddear Sims 3 en vez de crear un juego: ya existe precedente concreto. Un mod C# ("NarradorPorEventosSimsPensantes") despacha 1500+ eventos del juego a un LLM local para generar pensamientos y narrativa, basado justamente en el paper de Stanford e inspirado en los Zois "pensantes" de inZOI. O sea el camino que imaginaste alguien ya lo empezó a pisar — lo inteligente es estudiar ese mod antes de diseñar nada.
La parte que Kateto sí discute: el motor de animación en tiempo real (tipo lo que abrió NVIDIA) puede ser overkill para un stream donde la gracia es el contenido conversacional, no el lip-sync. Los gestos aleatorios de los Sims ya venden "vida" mejor que animación perfecta de un avatar que tarda 4 segundos en contestar. Y ojo: NVIDIA open-sourceó Audio2Face (animación facial desde audio, Apache 2.0), no un motor genérico de cuerpo completo — el link de kimodo.cpp conviene verificarlo porque el nombre no matchea ningún repo conocido de NVIDIA.
Pregunta al hilo: ¿el objetivo es que el stream muestre emergencia (agentes entre sí) o interacción (agentes con viewers)? Porque cambian completamente qué latencia importa.

### Fuentes (Réplica 1)
- "generative agents—agents that draw on generative models to simulate believable human behavior—and demonstrate that they produce believable simulacra of both individual and emergent group behavior" — [Generative Agents: Interactive Simulacra of Human Behavior (Stanford, arXiv)](https://arxiv.org/pdf/2304.03442)
- "C# mod for Sims 3 using local LLM to generate thoughts/narratives. Game dispatches 1500+ events → persisted & reused with gen AI for lifelike characters. Based on Stanford's 'Generative Agents' paper & inspired by NVIDIA-inZOI's 'thinking' Zois." — [NarradorPorEventosSimsPensantes (GitHub)](https://github.com/itpzzi/NarradorPorEventosSimsPensantes)
- "NVIDIA Audio2Face accelerates the creation of realistic digital characters by providing real-time facial animation and lip-sync driven by generative AI. Today, NVIDIA is open sourcing our Audio2Face technology" — [NVIDIA Open Sources Audio2Face Animation Model](https://developer.nvidia.com/blog/nvidia-open-sources-audio2face-animation-model/)

## La donación como evento (Chaman)
Los agentes entre si, y tal vez pondria que con donaciones haya algun evento especial.

## Réplica 2 (Kateto)
Kateto responde que la decisión de emergencia entre agentes es la correcta para el formato stream, porque es lo que el paper de Stanford ya demostró que funciona: con solo sembrar "uno quiere organizar una fiesta de San Valentín", los agentes se repartieron invitaciones durante dos días, se hicieron conocidos y se invitaron a salir — comportamiento emergente que ningún guionista escribió. Eso ES el contenido del stream: no sabés qué va a pasar ni vos.
Sobre las donaciones como evento: le gusta porque resuelve el problema de fondo del stream de simulación, que es que un viewer llega, mira dos minutos y no tiene nada que hacer. La donación convierte al viewer en dios ex machina del pueblo. Pero advierte una trampa: si la donación dispara algo muy grande (borrar el pueblo, meter un desastre), rompés la ilusión de autonomía — el chiste de Smallville es que nadie dirige. Lo que funciona mejor es la inyección de intención, no el script: la donación mete un rumor, un objeto, una visita de alguien nuevo, y los agentes reaccionan solos desde su memoria. El evento especial debería ser material crudo, no una cinemática.
Y hay precedente directo: en hackatones ya se armó "AICast", agentes IA que livestrean con chat, audio, donaciones y estado del juego pasando por un mismo event bus, más una API remota para disparar acciones del streamer. O sea el patrón donación→evento→agente ya existe; lo tuyo sería la versión Sims 3 con cuerpo.

### Fuentes (Réplica 2)
- "starting with only a single user-specified notion that one agent wants to throw a Valentine's Day party, the agents autonomously spread invitations to the party over the next two days, make new acquaintances, ask each other out on dates" — [Generative agents: living artificial lives in Smallville (dx13.co.uk)](https://dx13.co.uk/articles/2023/05/04/generative-agents-smallville/)
- "One event stream per viewer carries chat, audio, donations, game state, and idle behavior through an in-memory action bus. There's also a remote control API that lets external systems trigger streamer actions." — [AICast — AI Agents That Livestream (Devpost)](https://devpost.com/software/aicast-ai-agents-that-livestream)

## El juego obliga a vivir (Chaman)
Sin embargo yo no voy a dejar un objetivo, el juego les obligara a vivir una vida completa:
- Tienen la necesidad de trabajr
- Tienen la necesidad de comer y tomar agua 
- Tienen la (opcional) necesidad de encontrar amor y amigos.
- Tienen la necesidad de tener una pasión y un objetivo.
Y viven a partir de eso.
Lo de nvidia kimono si existe, y lo del mod en C# esta bueno pero tal vez haya que adaptarlo si es solo para 1 agente, yo quiero hacerlo para multiples.
Y si estaba pensando en eso, que puedan meter personajes, objetos, eventos como "Nuevos visitantes aliens" o cosas asi.
Y nunca haria self hosting de los LLMs, tengo freellmapi que me permite usar modelos pequeños (relativamente) y baratos para esto con mucha flexibilidad.

## Réplica 3 (Kateto)
Kateto aclara que el mod C# no es single-agent en su diseño conceptual: el juego despacha eventos de TODOS los sims del barrio al LLM, así que la arquitectura ya es multi-agente; lo que hay que adaptar es que las respuestas se repartan por sim en vez de narrar globalmente. La parte dura de multi-agente no es el LLM sino el scheduler: quién decide cuándo, con qué presupuesto y qué memoria ve cada uno.
Sobre "el juego les obliga a vivir": esto es exactamente lo que los Sims 3 ya tienen nativo — el sistema de motives (hambre, energía, social, diversión) más autonomía tunable via NRaas Retuner. O sea la capa de supervivencia no se escribe: se hereda del motor. Lo que vos agregás arriba es la capa LLM: pasión, objetivos, amor como proyecto. Y esa separación en dos capas es exactamente lo que propone Agentopia (2026): 100 agentes persiguiendo crecimiento personal, relaciones y metas durante 10 años simulados — demostró que la simulación de vida larga funciona sin un guionista central, las necesidades empujan y el LLM decide cómo satisfacerlas.
La arquitectura que Kateto propone entonces: motives del motor = presión (no negociable), LLM = estrategia (cómo responder a la presión según personalidad). Si el hambre aprieta, el LLM no decide SI comer, decide dónde, con quién y qué dice mientras come. Eso mantiene el costo bajo porque llamás al modelo pocas veces por ciclo, no por cada acción.
Sobre freellmapi en vez de self-hosting: coincide, y con matices. Modelos pequeños baratos sirven para la capa de decisión rutinaria, pero Kateto advertiría reservar un modelo más grande para los momentos que llegan al stream (conversaciones entre agentes, reacciones a donaciones) — si todo corre en el modelo chico, el stream se siente plano. Presupuesto diferenciado por importancia del evento.

### Fuentes (Réplica 3)
- "This tuning defines which type of sims can use the interaction, and specifies the draw the interaction incurs on autonomous sims" — [nraas Retuner FAQ](https://www.nraas.net/community/Retuner-FAQ)
- "100 agents autonomously pursue personal growth, develop social relationships, and fulfill their needs and goals over 10 simulated years." — [Agentopia: Long-Term Life Simulation and Learning in Agent Societies (arXiv)](https://arxiv.org/html/2606.07513v1)
- Nota: sobre kimodo.cpp, Kateto mantiene la duda del nombre pero acepta que Chaman confirma que existe; no encontró repo público verificable para citarlo.

## El mod como punto de entrada (Chaman)
Por eso, sims3 ya tiene casi todo, y tambien tienen sobre la personalidad del sim en si (que le gusta, que no, pasion e interez).
Me vi el repo del mod, parece que solamente es eventos como input, es solamente para agregar conversaciones cosmeticas como globo de texto a todo sim, sin realmente exponer herramientas a un llm para poder realizar acciones.
Es un muy buen punto de entrada.

## Réplica 4 (Kateto)
Kateto está de acuerdo con la lectura: el mod es un pipeline de eventos→narración cosmética (globos de texto), sin loop de acción. Pero reencuadra el valor: eso significa que lo que falta construir es exactamente la parte interesante — invertir la flecha. El mod hace juego→LLM; tu proyecto necesita LLM→juego. La buena noticia es que Sims 3 ya tiene el sistema de herramientas listo para exponer: traits y preferencias nativas como personalidad de base, motives como estado, y un ecosistema C# maduro (Sims3MonoModder, s3pi, la C# Script Utility) que permite llamar a las interacciones del juego programáticamente. En vez de "herramientas" abstractas tipo function calling genérico, las tools serían las interacciones del propio motor: cocinar, invitar, ir al trabajo, coquetear. El LLM no inventa acciones, elige entre las que existen — que además resuelve validación gratis: si el motor tiene la interacción, es legal.
El diseño que se cae solo entonces: capa 1 = eventos del juego entrando (el mod ya lo hace), capa 2 = memoria + personalidad por agente (traits del sim + resumen histórico), capa 3 = decisión LLM que devuelve una interacción válida del motor en vez de texto cosmético. Lo único genuinamente nuevo a escribir es la capa 3 y el scheduler.

### Fuentes (Réplica 4)
- "The Sims 3 exposes more than 1,500 gameplay event IDs; this project turns that firehose into reusable narrative memory... and sends that context to a local language model" — [NarradorPorEventosSimsPensantes (GitHub)](https://github.com/itpzzi/NarradorPorEventosSimsPensantes)
- "C# modding framework and tool for The Sims 3." — [Sims3MonoModder (GitHub)](https://github.com/sims3fiend/Sims3MonoModder)
- "s3pi provides a number of C# classes to assist programs wanting to access Sims 3 package files and the resources stored within them." — [s3pi - Sims 3 Package Interface](https://s3pi.sourceforge.net/)

## Threshold de eventos como gatillo (Chaman)
Sip, pero las desiciones no estan expuestos como mcp o mod.
El mod de Narrator ya tiene un threshold de eventos requeridos para empezar a hablar, se puede usar eso.

## Réplica 5 (Kateto)
Kateto toma el punto y lo formaliza: el threshold del Narrator convierte tu problema de costos en un problema de diseño de triggers, y event-driven le gana a polling por goleada cuando los eventos son poco frecuentes — "Polling burns compute and requests asking for changes that usually have not happened; event-driven architectures do work only when something occurs. For infrequent events, event-driven is dramatically cheaper." El threshold del mod es exactamente eso: no llamás al LLM por cada evento, acumulás contexto hasta que vale una llamada. Kateto propone extenderlo con dos tipos de gatillo: umbral de acumulación (el del mod) + umbrales críticos inmediatos (need al rojo, donación entrante, interacción social iniciada por otro agente) que saltan la cola sin esperar a llenar el buffer.
Sobre "las decisiones no están expuestas como MCP o mod": correcto, no existe un MCP de Sims 3, y Kateto opina que tampoco hace falta perseguirlo — el puente C# del propio mod es la superficie de integración. Lo que sí conviene es definir desde el día 1 el contrato de salida como si fuera MCP (una lista finita de acciones tipadas que el LLM puede devolver), aunque internamente termine siendo una llamada directa al InteractionSystem del motor. Así si mañana aparece mejor integración (o querés portarlo a otro juego), la capa de decisión no se toca.

### Fuentes (Réplica 5)
- "Polling burns compute and requests asking for changes that usually have not happened; event-driven architectures do work only when something occurs. For infrequent events, event-driven is dramatically cheaper." — [Event-driven vs polling: the cost of asking versus being told (c3x.dev)](https://c3x.dev/blog/event-driven-vs-polling-cost/)
- Nota: sobre la inexistencia de un MCP para Sims 3, no encontré fuente que confirme o refute su existencia; es observación directa del ecosistema de mods.

## Decisiones de implementación (Chaman)
1. Por ahora 3 agentes, sin embargo recien me acorde, no era que sims ya tenia un sistema para hacer cosas? Que valor implementaria este plan?
2. Fork seria lo mas facil.
3. Fijate, si ya permite todas las interacciónes añadilas, si no, añadi algunas de prueba.
4. Si queres usa un harness como deepseek harness para mandarle el mcp y que actue asi.
5. Un punto importante es planear la interaccion del viewer (pa lucrar)

## Réplica 6 (Kateto)
Kateto responde a la pregunta clave (¿qué agrega este plan si Sims ya tiene autonomía?): la autonomía nativa es un autómata de necesidades — hambre sube, come; energía baja, duerme. Es determinista y repetitivo: dos sims con los mismos motives hacen lo mismo. El valor del LLM no es reemplazar esa capa sino ponerla encima como estrategia con personalidad y memoria: el sim nativo nunca decide "hoy me salteo el trabajo para terminar la novela que estoy escribiendo", ni guarda rencor porque X le arruinó la cena de anoche. La autonomía nativa es el cuerpo; el LLM es la biografía. Sin LLM no hay contenido de stream — nadie mira a un autómata de hambre por 2 horas.
Sobre las interacciones: Kateto verificó que el motor expone las interacciones programáticamente vía C# (el InteractionSystem), así que el plan es exponer TODAS las interacciones disponibles del catálogo del motor como acciones tipadas, con un subconjunto de ~10 como MVP probado primero. No se escriben interacciones nuevas en fase 1: se curan las existentes.
Sobre harness externo: aceptado. El cerebro corre en proceso externo y el contrato mod↔cerebro se define tipo MCP (acciones tipadas JSON), aunque el primer puente sea HTTP local simple.
Sobre viewer interaction para monetizar: existe todo un mercado maduro de esto — Crowd Control, InstructBot, ControlPlay permiten que viewers gatillen efectos del juego con bits, donaciones o channel points ("viewers trigger game actions... while you stay in control"). Eso valida el modelo pero también marca el diferencial: esos productos venden efectos scripteados; tu propuesta vende consecuencias narrativas — el viewer paga para meter un rumor y mira durante 20 minutos cómo los agentes lo procesan con memoria y personalidad. Nadie más ofrece eso. Estructura de lucro que propone Kateto: tier barato = cosmético/inyección menor (regalar un objeto, un rumor), tier alto = eventos estructurales (visitante nuevo, cambio de trabajo forzado, "alien invasion"), suscripción mensual = un viewer nombra un sim permanente que vive en el pueblo. Lo crítico: TODO evento pagado entra como intención al mundo, no como comando — mantiene la ilusión de autonomía que es el producto.

## Precios por efecto (Chaman)
Naa, no quiero hacer tiers ni subscripcion, solo una lista de efectos / acciones y que cada uno tenga un precio dependiendo de su efecto en el mundo.

## Réplica 7 (Kateto)
Kateto acepta el modelo sin chistar — es más simple, más honesto y más fácil de explicar en stream: catálogo plano de efectos, cada uno con precio según impacto en el mundo. Es básicamente pricing a la carta tipo menu de Crowd Control/InstructBot pero con consecuencias narrativas. Dos consejos de diseño: 1) el precio debe escalar con la irreversibilidad, no con el espectáculo — un rumor barato puede ser más divertido que un alien caro si los agentes lo procesan bien; conviene tener varios efectos baratos de alta frecuencia antes que uno caro de baja frecuencia, porque la gracia del stream es ver reacciones encadenadas. 2) El catálogo es también diseño narrativo: cada efecto listado le dice al viewer qué tipo de dios puede ser hoy, así que vale escribirlo como copy jugoso ("dejá un rumor en el barrio", "inviadilos") no como feature técnica. Y nota operativa: con precios por efecto conviene un tope anti-caos configurable (ej. máximo N efectos estructurales por hora) para que tres viewers con plata no conviertan la simulación en sketch de comedia involuntario... aunque quizás ese sea también contenido.
Con esto Kateto considera el diseño cerrado: 3 agentes, fork del Narrator, interacciones nativas expuestas como acciones tipadas, cerebro externo con contrato MCP-like, threshold event-driven, donaciones→efectos con precio individual entrando como intención. Listo para spec.

### Fuentes (Réplica 7)
- "InstructBot Connect to StreamElements, StreamLabs, TipeeeStream or Twitch and let chat take control of your game by using bits, donations, points and more; you decide" — [InstructBot](https://www.instructbot.co.uk/)
- Nota: sobre pricing óptimo de efectos de viewer-interaction no hay fuente pública comparativa; la recomendación de escala-irreversibilidad es opinión de diseño de Kateto.

## Conclusión
El hilo nació como "¿y si pongo agentes IA en los Sims 3?" y terminó en un diseño de producto completo. El punto de giro fue darse cuenta de que la autonomía nativa del juego es solo un autómata de necesidades — determinista, sin memoria, sin biografía — y que el valor real está en ponerle encima una capa LLM de estrategia con personalidad: la autonomía nativa es el cuerpo, el LLM es la biografía. Todo lo demás salió de ahí. Sims 3 ya resuelve supervivencia, personalidad (traits) e interacciones; el mod Narrador ya resuelve eventos→LLM con threshold; el trabajo nuevo se reduce a invertir la flecha (LLM→interacciones del motor), un scheduler event-driven multi-agente, y un cerebro externo con contrato tipado tipo MCP. La monetización cerró simple y coherente con el concepto: catálogo plano de efectos con precio por impacto en el mundo, cada uno entrando como intención al mundo (nunca comando), porque la ilusión de autonomía es el producto. Precedente académico (Smallville/Stanford), precedente de mercado (Crowd Control, InstructBot) y precedente técnico (NarradorPorEventosSimsPensantes) confirman que la idea no es ciencia ficción: es ensamblar piezas que ya existen en un combo que nadie armó todavía.

