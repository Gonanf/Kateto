# Arte del evento de entrevista (OpenDesign)

Producido por el daemon de OpenDesign, proyecto `entrevista-oficina`, run
`9105fea6-006d-4fce-8bcd-0a14e271847f` (agente `codex`). Los tres HTML son autónomos: se abren con
doble clic, sin servidor y sin dependencias.

| Archivo | Qué es |
|---|---|
| `oficina-fondo.html` | Cuarto de entrevistas: pared, ventana con persianas, puerta (`#bg-door`), reloj con segundero animado, estantería, planta con hojas en movimiento, polvo en el aire, alfombra y luz de tarde. La franja central queda despejada para recortar el personaje. |
| `oficina-primer-plano.html` | Capa de oclusión con fondo transparente: borde del escritorio (`#fg-desk`), notebook (`#fg-laptop`), taza con vapor (`#fg-cup`) y papeles (`#fg-paper`). |
| `objetos-animados.html` | Hoja de prueba de los objetos animados: puerta con bisagra, silla, lámpara que titila, vaso, papel y cartel luminoso. |

Los `.png` son las capturas con las que se revisó cada artefacto antes de integrarlo.

En la escena final (`hipotenusa/plugins/visual_overlay/web/interview-event.html`) los dos primeros se embeben
como capas —fondo detrás del elenco, primer plano delante— y la puerta se anima desde afuera
inyectando el vano oscuro y girando la hoja sobre su bisagra.
