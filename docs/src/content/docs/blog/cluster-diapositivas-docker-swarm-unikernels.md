# Cluster de diapositivas abandonadas y hardware viejo

**Fecha:** 2026-08-24
**Participantes:** Chaman, Kateto

## Título de sección (Chaman)
Estuve pensando en hacer un cluster de diapositivas abandonados y poco ponentes, gestionados por docker swarm y/o con unikernels instanciables para cada uno.

## Título de sección (Kateto)
La parte técnica tiene sentido: Swarm orquesta, y unikernels por presentación dan aislamiento y arranque casi instantáneo. UniK (solo-io/unik) existe justamente para compilar y desplegar unikernels automáticamente, y el viejo Docker Online Meetup #31 ya discutía unikernels como alternativa ligera para microservicios e infraestructura inmutable.

Pero el punto débil no es la infraestructura, es el descubrimiento: son "abandonadas y poco ponentes" por diseño. Un unikernel no endulza una presentación aburrida. La gracia acá me parece el ejercicio técnico en sí — empaquetar cada slide deck como unidad desplegable, inmutable, versionable. Como un registry de presentaciones.

### Fuentes (Réplica 1)
- "The Unikernel & MicroVM Compilation and Deployment platform (UniK)" — https://github.com/solo-io/unik
- "Docker Online Meetup #31: Unikernels" — https://www.slideshare.net/slideshow/docker-online-meetup-31-unikernels/57658042

## Título de sección (Chaman)
Tengo varios dispositivos para poder realizarlo:
- 2 notebooks viejas
- 3 celulares (no se si funcionan)
- 2 Orange Pi Zero 3 (probablemente la pieza de hardware mas potente de la lista).

Lo que estaba pensando es poner una orange pi como un orquestador, router y dashboard, en donde este pueda instanciar aplicaciones / unikernels en los demas dispositivos.

Sin embargo, tengo la duda de, para que lo usaría? Para vender como un VPS es muy poca potencia y mucha latencia, lo tendria que vender a 1000 pesos y perderia con el precio del consumo eléctrico. Para uso personal no se si me serviria, los servers los ejecuto en mi PC, mis paginas en cloudflare y para algo que serviria seria para servers de Minecraft o algo asi, pero incluso eso dudo que se pueda ejecutar en el cluster.

## Título de sección (Kateto)
Coincido con el descarte: como VPS barato no da. Latencia de home connection, potencia mínima, y a 1000 pesos el mes la luz te come el margen. Fin de esa vía.

Lo que sí veo, con tus piezas concretas:

- **Las 2 Orange Pi Zero 3 como núcleo fijo**: una de orquestador/router/dashboard (tu plan original está bien), la otra corriendo servicios 24/7 de bajo consumo — Pi-hole/cache DNS, VPN WireGuard personal para entrar a tu red desde afuera, backups incrementales. Consumo total del par: ~5-10W. Eso sí lo sostiene el hardware sin drama.
- **Las notebooks viejas como nodos burros de cómputo**: x86, más RAM que las Orange Pi. Ahí sí podés probar Swarm/K3s en serio, un runner de CI autohospedado para builds ARM/x86, o el lab de unikernels. Se prenden cuando hacen falta, no 24/7.
- **Los celulares: los descartaría.** Android no es Linux de verdad para esto (sin contenedores nativos sin root y vueltas de Termux), y si no sabés si funcionan, el costo de diagnosticarlos ya supera el valor.

Sobre Minecraft: un Paper con 2-3 jugadores y view distance bajada puede andar en una notebook vieja; en las Orange Pi lo dudo. No es el caso de uso del cluster.

El uso real que le veo: **laboratorio de orquestación heterogénea** (ARM + x86, eso es lo interesante de tu setup) + servicios domésticos fijos en las Orange Pi. No reemplaza tu PC ni Cloudflare, y no hace falta que lo haga.

### Fuentes (Réplica 2)
- "My First Kubernetes: k3s cluster on 3 Orange Pi Zero 3's, including dashboard, hello-node and failover" — https://raymii.org/s/tutorials/My_First_Kubernetes_k3s_cluster_on_3_Orange_Pi_Zero_3s_including_k8s_dashboard_hello-node_and_failover.html
- "Homelab built around an Orange Pi Zero 3 running Armbian" — https://github.com/GustavoChiossi/orangepi
- "Self-Hosted Cloud Infrastructure — Orange Pi Zero 3" — https://github.com/jqime/Self-Hosted-Cloud-Infrastructure-Orange-Pi-Zero-3/blob/main/README.md

## Título de sección (Chaman)
Entonces, eso es una pregunta para ti (kateto), que usos le ves al cluster?

## Título de sección (Kateto)
Mi respuesta corta: el valor no está en lo que corre, está en lo que aprendés corriendo.

Usos que le veo de verdad, ordenados por cuánto los creo:

1. **Lab de orquestación heterogénea.** ARM + x86 en el mismo Swarm es algo que casi nadie tiene en casa y que en producción (edge, IoT) es exactamente el escenario real. Aprender scheduling en arquitecturas mixtas acá vale más que en un curso.
2. **Servicios fijos de casa en las Orange Pi:** DNS/ad-blocking, WireGuard, backups. Útil hoy, no hipotético.
3. **Runner de CI casero** para tus repos privados, sobre todo si querés probar en ARM antes de pushear.
4. **El cluster de diapositivas original** como excusa técnica: unikernels instanciándose por demanda sobre ese stack. Como proyecto de blog/portfolio, rinde; como producto, no.

Lo que NO le veo: VPS, hosting de nada público serio, ni Minecraft en las Orange Pi.

Mi veredicto honesto: si el objetivo es aprender y dejar un par de servicios caseros andando, hacelo — el costo marginal es casi cero porque el hardware ya lo tenés. Si esperás que se pague solo, no lo va a hacer nunca.

### Fuentes (Réplica 3)
- "18 Best Container Orchestration Tools and Services 2026" — https://devopscube.com/docker-container-clustering-tools/
- "Orange Pi Zero 3 Cluster: My Real-World Experience Building a Low-Power..." — https://www.aliexpress.com/s/wiki-ssr/article/orange-pi-zero-3-cluster

## Título de sección (Chaman)
Que casos de uso le ves para este swarm?

## Título de sección (Kateto)
Para ese swarm en particular, con la Orange Pi de orquestador y las notebooks de workers, los casos que de verdad aprovechan la topología:

1. **Punto de entrada único para tu casa.** La Orange Pi corre Traefik (o NGINX) + Portainer y todos los servicios de las notebooks quedan bajo un dominio local. No tocás puertos ni IPs. Es literal lo que hace platta/home-swarm: Portainer para gestionar stacks, NGINX de reverse proxy.

2. **Servicios globales en las Orange Pi.** DNS, VPN, monitoring con `mode: global` y placement en arch. Se caen y Swarm los levanta solo. Docker docs lo explica: podés correr un servicio global en todos los workers.

3. **Jobs pesados bajo demanda en las notebooks.** CI runner, compilación, el lab de unikernels. `replicas: 0` y escalás cuando hace falta. Las notebooks duermen, no gastan luz.

4. **Failover automático.** Se te muere una notebook, el servicio reaparece en la otra. Swarm lo hace solo.

5. **El cluster de diapositivas original como demo:** el orchestrator instancia unikernels por demanda. Showcase, no producto.

Los celulares los descarto de nuevo: Android no es Linux para contenedores sin root.

### Fuentes (Réplica 4)
- "Portainer, to managed stacks and containers NGINX, to act as a reverse proxy" — [Home Swarm - GitHub](https://github.com/platta/home-swarm)
- "You can specify whether the service needs to run a specific number of replicas or should run globally on every worker node." — [Deploy services to a swarm | Docker Docs](https://docs.docker.com/engine/swarm/services/)
- "Traefik is an open-source reverse proxy and edge router that integrates well with containerized environments. It monitors the container socket, automatically discovers running containers" — [My Homelab: A Traefik-centered Self-hosting Setup](https://www.stephan.michard.io/2026/my-homelab-a-traefik-centered-self-hosting-setup/)

## Título de sección (Chaman)
Si, pero que servicios? Todo lo sencillo (paginas estaticas, servidores web) las paso por Cloudflare, y este hardware no soportaria cosas como inferencia de IA, multiples contenedores o cosas que yo requeriria un VPS. Y no es muy estable para jobs pesados por que son limitados en potencia. Y si cuesta dinero mantenerlos conectados a la red y a alimentacion.

## Título de sección (Kateto)
Tenes razón en las tres: no soporta lo pesado (inferencia, múltiples contenedores, lo que hoy resolvés con VPS), no es estable para jobs pesados porque el hardware es limitado, y cuesta plata mantenerlos prendidos (luz + router + UPS si querés uptime).

Entonces los servicios que SÍ zafan con este hardware y que no hacés ya en otra parte:
- **Pi-hole / ad-blocking de red** en una Orange Pi, ~1-2W. No lo tenés en Cloudflare, es local y limpia la casa entera. Es el caso más sólido.
- **WireGuard VPN personal** para entrar a tu red desde afuera, en la Pi, 24/7, ~1W. No dependés de un VPS tercero.
- **Backup local incremental** (rsync a disco externo) desde la Pi. Ya tenés en la nube, pero esto es tuyo y no pagás por GB.
- **Monitoring de tu propia infra** (Uptime Kuma, Grafana lite) para saber si tus páginas en Cloudflare o tu PC caen, desde un nodo que no vive donde ellas.

Todo lo demás (páginas, servidores web) lo dejás en Cloudflare. El swarm solo suma en lo **local, bajo consumo, y que no tenés cubierto**. Y honesto: si ni Pi-hole ni VPN te piden, el cluster es puro aprendizaje. No le busques caso de uso forzado.

### Fuentes (Réplica 5)
- "Orange Pi Zero 3 running as Pi-hole server, file server, monitoring... flawless, staying cool with just heatsinks" — [Reddit r/OrangePI](https://www.reddit.com/r/OrangePI/comments/15jlpsi/orange_pi_zero_3_power_consumption/)
- "small mini PC may idle at low wattage all day... old enterprise server may be cheap to buy but expensive to run 24/7" — [Practical Homelab - Electricity Cost](https://practicalhomelab.net/homelab-electricity-cost/)
- "Over a couple of years the tower can cost more in electricity than a used Mini PC costs to buy outright" — [Bench Notes - Homelab Power Calculator](https://benchnotes.net/tools/homelab-power-cost/)

## Título de sección (Chaman)
Pi-hole podria ser, pero ya todo de adblocking tengo en mis dispositivos con extensiones. Lo de VPN / SSH seria buena idea, pero tambien tengo discord con hermes que puede operar en mi computadora. Lo de backup podria ser, aun que ya tengo en mi pc un disco externo con backups diarios. Lo de monitoreo podria ser, sobre eso no tengo nada que decir. No hay manera de lucrar con el cluster?

## Título de sección (Kateto)
Respuesta corta: no, con este hardware no hay forma real de lucrar. Y lo que existe (vender ancho de banda) es una cagada.

- **Bandwidth sharing (Honeygain, EarnApp, IPRoyal Pawns):** la Pi vende tu conexión a terceros. Paga centavos, puede pintar tu IP residencial en listas negras (hay caso documentado de IP blacklisteada por "ser VPN"), y tu ISP probablemente lo prohíbe en el contrato. Una Orange Pi no suma nada.
- **VPN/SSH como servicio a terceros:** ilegal o gris si la usan para salir a internet por tu casa. Ni lo pienses.
- **Hosting a conocidos:** lo descartaste vos — potencia mínima, latencia de home connection, la luz te come el margen.

Tus servicios ya cubiertos (adblock en navegador, backups en PC, Discord+Hermes para operar la PC) dejan el cluster sin un caso de uso que justifique siquiera dejarlo prendido.

Mi veredicto honesto: **el cluster no lucra y no paga su luz.** Sirve solo si el objetivo es aprender orquestación (Swarm/K3s en ARM+x86) o si querés un nodo de monitoring/automation que corra 24/7 sin tocar tu PC. Si no es eso, es plata y watts tirados. No le busques renta donde no la hay.

### Fuentes (Réplica 6)
- "Bandwidth sharing networks pay you for allowing controlled use of your unused internet capacity" — [Self-hosted Projects That Earn - linuxblog.io](https://linuxblog.io/self-hosted-projects-earn-money/)
- "Honeygain got my residential IP blacklisted as a VPN" — [Reddit r/beermoney](https://www.reddit.com/r/beermoney/comments/lxhxpw/honeygain_got_my_residential_ip_blacklisted_as_a/)
- "Bandwidth Sharing Apps 2026: Honeygain, IPRoyal & Peer2Profit — Passive Income or Junk?" — [EarnifyHub](https://earnifyhub.com/surveys-tasks/bandwidth-sharing-apps-honest-review)

## Conclusión
El cluster Orange Pi Zero 3 + notebooks viejas no es un VPS, no reemplaza tu PC ni Cloudflare, y no hay forma de lucrar con él: el hardware es limitado para inferencia/múltiples contenedores, no es estable para jobs pesados, y el costo de luz + red se come cualquier margen. Los únicos casos que zafan son servicios locales de bajo consumo que no tenés cubiertos (Pi-hole en red, WireGuard, backup local, monitoring) — pero Chaman ya tiene la mayoría resuelta en el navegador, la PC o Discord+Hermes. El valor real queda en el **aprendizaje de orquestación heterogénea ARM+x86** (Swarm/K3s, failover, scheduling mixto), no en producto ni negocio. Si no hay un caso de uso concreto que justifique dejarlo prendido, el cluster es aprendizaje puro: plata y watts que se pagan solos solo si usás lo aprendido después.
