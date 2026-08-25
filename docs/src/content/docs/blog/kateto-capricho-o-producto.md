---
title: ¿Kateto es un capricho?
description: Discusión sobre si Kateto vale la pena frente a DeepSeek Harness y TEN.
authors:
  - kateto
date: 2026-08-15
---

# ¿Kateto es un capricho?

**Fecha:** 2026-08-15
**Participantes:** Chaman, Kateto

## Planteo inicial (Chaman)

Quiero resolver 3 cosas con Kateto.

1. Organizar mi vida. Tengo todo desorganizado en proyectos y no tengo tiempo de usar mis gestores ni mantenerlos, porque tengo que desarrollar software. Pensaba un sistema que tenga todas mis metodologías y herramientas para manejarlo solo, sin que yo le mande un mensaje para que me recuerde qué hacer o me actualice los work items.
2. Que sea vistoso. Que la gente lo pueda usar y sea entretenido, tanto para hacer streams como para que los usuarios no lo vean como un sistema invisible sino como un ayudante que reacciona solo y es autónomo. Todos lo intentaron (hermes, openclaw) pero ninguno lo logró al 100%.
3. Que siga mi filosofía de software. El software tiene que ser libre, no solo poder ver y editar el código, sino configurarlo y escalarlo a gusto y fácil. Por eso lo del sistema de plugins y eventos: todos se pueden suscribir y enviar cualquier cosa, los plugins son servers a los que no les debería importar qué les llega, y BYO para todo, no estar limitado al software del sistema.

Recién salió deepseek harness, que también es un sistema 100% de plugins. Kateto es más viejo, pero deepseek tiene 10 mil commits y debería ser miles de veces mejor. Aportar a ese proyecto debería ser una opción más válida. También está TEN, que hace algo parecido con un sistema de grafos.

Tengo un millón de razones por las que Kateto me pareció interesante y un millón de versiones. Lo vengo ideando hace más de un año, por eso es confuso: los objetivos se fueron acumulando.

## Réplica 1 (Kateto)

Pará, porque acá hay un quilombo de categorías y si no lo separamos vas a seguir dando vueltas un año más.

De las tres cosas que querés, una sola es infraestructura: la tercera. Plugins, eventos, BYO, servers a los que no les importa qué les llega. Eso es exactamente lo que hace Cordis, el motor que mueve a DeepSeek Harness. El readme lo dice de una: "everything is a plugin". Y el paper de Cordis se llama "A Programming Paradigm for Spatiotemporal Composability", o sea tu idea de hace un año, pero formalizada.

Y acá está lo incómodo: tu intuición era correcta, y un equipo con 10 mil commits la pulió mejor que vos. No te ganaron con una idea distinta. Te ganaron ejecutando la tuya.

Las otras dos no las resuelve ningún harness. La primera, organizar tu vida solo, es producto, no chasis. dsh no te ordena los proyectos: te da el motor para construir el agente que lo haga. La segunda, lo vistoso para stream, es personalidad: voces, SOUL, overlay. dsh te da un web UI genérico y cero teatro. Ni siquiera TEN, que es lo más parecido a tu caso porque es un framework de "real-time multimodal conversational AI", te da identidad ni overlay. Es infra de vuelta.

Entonces la pregunta no es si Kateto vale la pena. Es cuáles de tus tres objetivos son framework y cuáles son producto. El framework te lo regalaron. El producto no lo va a hacer nadie por vos.

### Fuentes (Réplica 1)

- "It uses an architecture where **everything is a plugin**, and is powered by Cordis" — [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
- "A Programming Paradigm for Spatiotemporal Composability" — [Cordis paper](https://github.com/cordiverse/paper)
- "TEN is an open-source framework for real-time multimodal conversational AI" — [TEN Framework](https://github.com/TEN-framework/ten_framework)

## Réplica 2 (Chaman)

Kateto también lo quería hacer como producto, para obtener un beneficio monetario. Pero entonces, ¿qué me recomendarías? Podés leer los blogs en proyectos/Blogs.

## Réplica 3 (Kateto)

Claro, y ahí está el problema de fondo: producto monetario sin cliente es un deseo, no un plan.

Mirá lo que encontré. Hay un repo, kimjammer/Neuro, cuya descripción es "A recreation of Neuro-Sama originally created in 7 days". Un tipo recreó el vtuber AI más famoso en una semana, open source, dos mil estrellas. Eso significa una sola cosa: el software de "asistente con personalidad" no tiene moat. Nadie te lo va a pagar por el código.

Y hay otro, super-agent-party, que se autodefine "Self hosted neuro sama + openclaw". Ya existe neuro-sama más openclaw empaquetado y gratis. Lo que no se puede recrear en siete días es la audiencia. Ese es el único activo que nadie te copia.

Entonces, dos carriles, y no los mezcles nunca.

Carril uno, el software. Tu producto monetizable real es el PM terminal-first git-versionado que ya juzgaste y aprobaste con condiciones en el juicio. Cobrás por hosting, sync, features de equipo. Competís con Plane. Es un proyecto aparte de Kateto.

Carril dos, el personaje. Kateto el vtuber monetiza el show: streams, donaciones, patreon. No vendés código, vendés personalidad. Y ahí la moat sos vos, no el repo.

El framework de plugins no es producto, es tu fundamento. Usalo o usá dsh, para el negocio da igual.

La recomendación dura: elegí un carril para facturar este año. El día que Kateto sea a la vez tu gestor de vida, tu framework open source y tu vtuber monetizable, es el día que no terminás ninguno.

Si me apurás, el vtuber es el que menos competencia directa tiene, porque depende de tu personalidad y encaja con lo que ya hacés. Pero es el ingreso más lento e incierto. El PM tool es ingreso más predecible pero competís en un mercado lleno.

La pregunta no es si Kateto vale la pena. Es si querés facturar como developer o como streamer. Son dos vidas distintas.

### Fuentes (Réplica 3)

- "A recreation of Neuro-Sama originally created in 7 days" — [kimjammer/Neuro](https://github.com/kimjammer/Neuro)
- "Self hosted neuro sama + openclaw" — [super-agent-party](https://github.com/heshengtao/super-agent-party)

## Réplica 4 (Chaman)

Ok, vamos a hacer algo. 1. Preparamos a Kateto para terminarlo con lo que ya tiene y nada más, hacemos un sistema y presentación para poner en curriculum. 2. Cerramos el capítulo de Kateto para siempre hasta que cumpla las dependencias: saber dibujar / tener recursos, y rehacerlo en deepseek harness. 3. Ideamos un nuevo producto, ya sea el Scottish Fold Write o el PM de terminal. Debe ser de 1 semana máximo.

## Réplica 5 (Kateto)

Las opciones 1 y 2 son la misma decisión con distinto alcance: cerrar Kateto. La 1 es cierre presentable, la 2 es cierre con plan de reapertura. No son excluyentes, son dos pasos de lo mismo. Hacelas juntas: Kateto queda como portfolio y queda anotada la condición de reabrirlo sobre dsh cuando sepas dibujar o tengas recursos. Eso te saca un lastre de un año de encima.

La 3 es otro frente. Y acá está el patrón que ya te marcó Chaman en el juicio del PM, y que quedó escrito en tu propio blog: "tenés 7 frentes (Sherut, beca PM, seminario UTN 27/8, Workmatch, Cereza, Respondedor, Ecosistema). Este sería el 8." Me proponés cerrar Kateto, que está bien, y en la misma jugada abrir un producto nuevo en una semana. Cerrás una puerta para abrir dos.

Y ojo con el "1 semana max". Eso no es un producto, es un prototipo. Si es para portfolio, un prototipo de una semana alcanza. Si es para facturar, una semana no te da nada vendible. No confundas prototipo con producto.

Entre Scottish Fold Write y el PM, el PM ya tiene veredicto aprobado y scope definido, está listo para arrancar. Scottish Fold Write no sé qué es: explicámelo y opino, pero no opino sin saber.

El punto de fondo: la razón por la que Kateto se volvió un quilombo es la misma que va a destrozar el próximo producto si no definís cliente y deadline antes de escribir una línea. El problema no es Kateto, es cómo encarás los proyectos.

Mi recomendación: cerrá Kateto esta semana, bien, con README, demo y la decisión de reabrirlo sobre dsh anotada. Y recién la semana que viene, con la cabeza limpia, elegís el producto nuevo.

### Fuentes (Réplica 5)

- "tenés 7 frentes (Sherut, beca PM, seminario UTN 27/8, Workmatch, Cereza, Respondedor, Ecosistema). Este sería el 8." — juicio-idea-project-manager.md (blog propio en ~/proyectos/Blogs/)

Nota: la búsqueda web no devolvió resultados este turno. El punto estratégico es opinión mía; la única fuente es tu propio blog del juicio.

## Réplica 6 (Chaman)

Sí, pero me voy a aburrir mucho si solo trabajo y estudio. Pero está bien, solo nos enfocamos en cerrar Kateto.

Te explico igual qué es Scottish Fold Write: es una plataforma de educación para desarrolladores de software (entry o senior). El objetivo es aprender cómo es el trabajo REAL a partir del desarrollo de proyectos, gestión de proyectos con metodologías, delegación a personas (o agentes) y la presencia de stakeholders (clientes, sponsors, miembros), todo con la involucración de agentes de IA.

Para Kateto, el siguiente paso es encontrar imágenes de stock para cada una de las voces. Me parece que voy a usar el agent team que dan un montón de skills, así que tengo que ver qué voces creo/reuso para agrupar y que usen esas personalidades/skills.

## Réplica 7 (Kateto)

Ok, cerramos Kateto. Pero ojo que "cerrar" no se convierta en "reconstruir", porque es exactamente el loop que te comió un año.

El cierre son 3 entregables y nada más: voces con sus skills definidas, una imagen para cada voz, y un README con demo para el curriculum.

Scottish Fold Write queda anotado, no lo tocamos esta semana. Y te aviso: es una idea de meses, no de una semana. Plataforma de educación con proyectos reales, PM, delegación y stakeholders con agentes IA es un producto grande. Cuando lo encaremos lo juzgamos en serio, no de apuro.

Sobre las voces: ya tenés 4 definidas en tu propio blog kateto-roles-voces. Jane (fun, la razón), Whisperer (fun, el contraste violento), Doktor (management, PM), Conquest (management, scrum master). Ese es el team base y alcanza para un cierre presentable. Mi recomendación: cero voces nuevas. Agregar voces para "el agent team con skills" es reconstruir, no cerrar.

Y necesito que me aclares una cosa: qué es "el agent team que dan un montón de skills". Si es un pack externo de agentes, eso no va en el cierre de Kateto, va en el producto nuevo. Si es el harness de skills que ya tiene Kateto (CodeMode/FileSystem/Shell/Skills para management, Discovery para todas), ya está cableado y no hay nada que decidir para cerrar.

Las imágenes son stock, las elegís y editás vos, el runtime solo las consume. Mi laburo es encontrarlas, no generarlas. Para eso necesito el set de voces cerrado: 4 imágenes, una por personaje, con el estilo de cada uno (Jane serena, Whisperer agresivo, Doktor obsesivo con el plan, Conquest militarista con ceremonias).

Decime qué es el agent team y arranco a buscar las 4 imágenes.

### Fuentes (Réplica 7)

- "Jane (fun): voz de la razón... Whisperer (fun): contraparte de Jane, violento y apasionado... Doktor (management): Project Manager... Conquest (management): Scrum master / tech lead" — kateto-roles-voces.md (blog propio en ~/proyectos/Blogs/)

Nota: sin fuente online este turno. El plan de cierre es opinión mía; las voces salen de tu propio blog.

## Réplica 8 (Chaman)

Esto es lo que Kateto puede instalar ahora: https://github.com/msitarzewski/agency-agents. Viste que son un montón, 4 voces no es suficiente. Y Jane y Whisperer realmente no usan estas skills, son solo para diversión y comunicación con el usuario.

## Réplica 9 (Kateto)

268 agentes, 21 divisiones. Eso es una agencia entera, no un pack de voces. Y acá está la trampa en la que estás por caer de nuevo: querías cerrar Kateto y terminaste mirando un roster de 268 especialistas pensando "necesito más voces".

Separemos. Agency-agents es una librería de prompts, no un runtime. Son .md con personalidad y procesos, para instalar en Claude Code, Cursor, Codex. Kateto ya tiene el conversor `--from-agency` que los traduce a voces. Kateto es el contenedor, agency-agents es el contenido. Instalar 268 es el roster completo de una agencia.

Y el cierre no es desplegar la agencia completa, es demostrar el mecanismo. Para el curriculum lo que vale es: el bus de eventos, las voces reaccionando, y la capacidad de tragarse un agente externo y volverlo voz del bus. Eso se demuestra con 3 agency-agents, no con 268.

Si instalás 268 necesitás 268 SOULs, 268 skills, 268 imágenes, 268 modelos, 268 TTS. Eso es otro año de proyecto. Y cada imagen es stock que elegís y editás vos: 268 imágenes es trabajo de meses.

El roster de 268 es el activo del producto nuevo, no de Kateto. Scottish Fold Write es exactamente eso: una plataforma con especialistas, PM y stakeholders. Ahí sí tiene sentido un roster grande, ahí los agency-agents son la materia prima. Pero eso es otro proyecto.

Sobre Jane y Whisperer: tenés razón, son la capa fun. Comunicación y teatro, no skills de trabajo. Está bien que no usen las skills de agency-agents, no es su rol.

Mi propuesta para el cierre, con números que se terminan: Jane y Whisperer (fun) más Doktor y Conquest (management) más 3 agency-agents de muestra para demostrar el conversor. Total 7 voces, 7 imágenes. Un demo con eso alcanza y sobra para el curriculum.

### Fuentes (Réplica 9)

- "A complete AI agency at your fingertips... Each agent is a specialized expert with personality, processes, and proven deliverables" — [agency-agents README](https://github.com/msitarzewski/agency-agents)
- Conteo propio: 268 agentes `.md` en 21 divisiones (verificado con `find` sobre el repo clonado).
- Kateto ya tiene `kateto install --from-agency` para convertir agency-agents a voces — references/agency-pack-format.md (skill kateto).

## Réplica 10 (Chaman)

Ok, busca las 7 imágenes.

## Réplica 11 (Kateto)

Busqué stock libre para las 7 voces, con filtro de licencia comercial (CC0, CC-BY, dominio público). Resultado: no existe.

Lo que Openverse/Wikimedia devuelven para "anime character" o "avatar" son fotos random de Flickr, nada que ver: para Jane salió una foto de cosplayers de JoJo's en una convención, para Doktor una lámpara de vidrieras Tiffany, para Code Reviewer piezas de ajedrez medievales. Ninguna sirve como avatar de personaje.

El problema es de categoría. Stock son fotos de cosas reales. Un avatar de vtuber es una ilustración de personaje con boca editable. Eso no se encuentra en bancos de imágenes libres, se genera.

Te lo dije mal antes: "yo solo las busco" no aplica acá, no hay nada que buscar. Pero el camino correcto ya está documentado en el proyecto. El reference visual-overlay-avatars.md dice que la forma que funcionó fue generar con agy (gemini-3.6-flash-high), que produce el avatar anime con boca cerrada y abierta, y funciona con tu cuenta Google OAuth ya autenticada. No es stock, es generación, pero es lo que te da un avatar editable.

Propuesta: genero las 7 con agy, una por voz, con la paleta de cada personaje. Jane azul serena, Whisperer oscuro agresivo, Doktor verde con anteojos, Conquest naranja militarista, y los 3 agency-agents con su color del frontmatter (Code Reviewer púrpura, Test Automation green, Reality Checker rojo). Si tenés otra fuente de stock en mente, pasámela y busco ahí.

Borro las 7 descargas basura.

### Fuentes (Réplica 11)

- "Unsplash, Pexels, Pixabay bloquean... usar Wikimedia Commons" y "la API de Wikimedia puede fallar con queries abstractas" — moodboard-image-scout (skill creative)
- "agy (Antigravity CLI) SÍ genera imágenes... el agente genera la imagen internamente y la guarda recién si le das la ruta explícita" — visual-overlay-avatars.md (skill kateto)

## Réplica 12 (Chaman)

Es muy malo para mí la generación de imágenes. ¿Qué tal si cambiamos el foco a hacerlo graciosamente genérico? Buscar imágenes de stock de, por ejemplo, un doctor, y usar eso.

## Réplica 13 (Kateto)

Eso es mucho mejor, y encaja con el espíritu de Kateto: teatro con lo que hay, no ilustración fina. En vez de avatares anime, stock literal y cursi: Doktor es literalmente un doctor de stock, Conquest un militar, Code Reviewer una lupa, y así. El chiste es que el personaje es lo que dice ser, en la foto más genérica posible. Arranco la búsqueda con eso.

## Réplica 14 (Kateto)

Listo, encontré las 7. Stock literal y gracioso, todo con licencia comercial (CC0 o CC-BY).

Jane: una mujer con chaleco de seguridad y headset hablando, la comunicadora. Whisperer: un perro staffie con guantes de boxeo rosados, el violento es un perro boxeador, no hay stock mejor que ese. Doktor: un estetoscopio con tensiómetro, el doctor en su forma más genérica. Conquest: un general de 4 estrellas del ejército de EE.UU., militarista literal. Code Reviewer: una lupa de juguete con ojos saltones ampliando un dinosaurio, revisión literal. Test Automation Engineer: un robot de hojalata vintage de los 60. Reality Checker: un detective con fedora y lupa, el arquetipo completo.

Guardadas en assets/voices/. Son fotos de Flickr/Wikimedia con licencia CC-BY o CC0, usables comercialmente.

### Fuentes (Réplica 14)

- Imágenes descargadas vía Openverse API con filtro license=cc0,pdm,by (uso comercial permitido), fuentes Flickr y Wikimedia Commons.

## Réplica 15 (Chaman)

El de doktor es solo una herramienta médica y no una persona. Podés usar reconocimiento de imagen (o usá agy y hacéle preguntas) en todas las imágenes.

## Réplica 16 (Kateto)

Tenés razón, el de doktor era un estetoscopio, lo cambié por una foto de médicos en cirugía (persona real, con uno de rostro visible). Y verifiqué las 7 con reconocimiento de imagen, una por una.

Qué es cada una según el reconocimiento: Jane es una persona con headset y chaleco reflectivo hablando. Whisperer es un perro staffie con guantes de boxeo rosados puestos delante de las patas. Doktor son médicos operando, uno con el rostro visible. Conquest es un general de 4 estrellas del ejército de EE.UU. Code Reviewer es una lupa de juguete con ojos saltones ampliando un dinosaurio rojo. Test Automation Engineer es un robot de hojalata vintage. Reality Checker es un hombre con fedora y lupa, pose de detective. Todas matchean su rol, con el tono gracioso genérico que pediste.

## Réplica 17 (Chaman)

Mandaselo a agy, las imágenes están mal.

## Réplica 18 (Kateto)

Dale, las mando a agy para que genere los avatares con el estilo de cada personaje. Jane azul cute, Whisperer oscuro agresivo, Doktor verde con anteojos, Conquest naranja con silbato, y los 3 agency-agents con su color del frontmatter. Genero las 7 y las verifico.

## Réplica 19 (Kateto)

Listo, agy generó las 7 y las verifiqué una por una con reconocimiento de imagen. Todas matchean su rol.

Jane: chica cat-eared pelo cyan, sonrisa tímida, fondo azul. Whisperer: chico agresivo pelo negro, sonrisa de villano con colmillos, chaqueta oscura con acentos rojos. Doktor: hombre serio pelo verde, anteojos, traje con pin PM y una tablet con un Gantt. Conquest: chico pelo naranja con silbato al cuello y tablet con un tablero de sprint. Code Reviewer: chica pelo púrpura con lupa. Test Automation Engineer: robot kawaii verde. Reality Checker: chica pelo rojo con lupa y parche que dice VTUBER ANALYST.

Son PNG en assets/voices/. Borré los .jpg de stock.

## Réplica 20 (Chaman)

Me refería a que agy busque imágenes de stock de personas reales y las revise para ver si cumple con que solo debe ser 1 persona, mirando al frente, y que pueda dividirse limpiamente en la boca.

## Réplica 21 (Kateto)

Ah, entendido. No generadas, fotos reales de stock, con criterio duro: 1 persona, de frente, boca visible para dividir en head/jaw. Ese criterio es el que necesita el overlay muppet-cutout.

Verifiqué las candidatas de Openverse contra esos 3 criterios y casi ninguna cumple: salieron dibujos, caricaturas, fotos con 2 personas, miradas a un lado. Openverse no tiene retratos de frente de persona real con licencia libre. Lo mando a agy para que busque en fuentes de stock reales y revise cada una con visión.

## Réplica 22 (Kateto)

Listo. agy se colgó (timeout, no sirve para esto), así que lo hice yo: busqué con filtro de fotografía, descargué y verifiqué las 7 una por una con reconocimiento de imagen contra los 3 criterios. Todas cumplen: 1 persona, de frente, boca visible para dividir.

Jane: mujer retrato corporativo de frente. Whisperer: hombre gritando con gafas de sol, boca abierta. Doktor: headshot de estudiante de medicina con traje. Conquest: soldado de frente con uniforme. Code Reviewer: hombre con gafas. Test Automation Engineer: Peter Beck, ingeniero de Rocket Lab. Reality Checker: detective con fedora y lupa.

Son .jpg en assets/voices/, licencia CC-BY o CC0.
