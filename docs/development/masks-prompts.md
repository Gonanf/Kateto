# Kateto Masks — SVG Generation Prompts

> Basado en: `concepts/avatars.md` — diseño de máscaras puppet-style, versión uncanny valley.
> Julio 2026.

---

## Concepto base

Todas las máscaras son **objetos físicos realistas** — se ven como máscaras de verdad hechas de porcelana, madera, cuero o metal. No son planas ni minimalistas. Tienen textura, profundidad, sombras, reflejos de luz.

Las máscaras cubren **media cara** (frente a labio superior) y tienen **huecos para los ojos grandes**, pero no están vacíos: dentro de cada hueco se ven **ojos humanos**, del mismo color que la máscara, con la esclerótica (el blanco del ojo) negra o gris oscura. Parece que hay alguien adentro — pero sus ojos dejan claro que no es humano.

**Reglas del sistema visual:**
- **Estilo realista** — no flat vector. Las máscaras tienen material, textura, sombras, brillo
- **Materiales:** porcelana, madera, cuero, metal, cerámica — según la voz
- **Ojos visibles dentro de los huecos** — ojos de tamaño humano, del mismo color que la máscara, con esclerótica negra/gris
- **Los ojos miran hacia adelante** — fijos, sin pestañear, como si la cosa dentro de la máscara estuviera observando
- **Sin iris ni pupila visibles** — solo el color sólido del ojo + esclerótica oscura
- **Boca** — sigue siendo una abertura (hueco negro recortado) con profundidad, no plana
- **Fondo transparente** — se renderizan sobre dark background
- **Factor uncanny valley esencial** — parecen reales, pero algo está mal

---

## Materiales por voz

| Voz | Material | Textura |
|-----|----------|---------|
| **Jane** | Porcelana blanca envejecida | Liso, satinado, pequeñas craqueladuras |
| **Doktor** | Madera pulida color hueso | Veta de madera fina, barniz mate |
| **Conquest** | Porcelana rota | Grietas visibles, bordes astillados |
| **Narrador** | Cerámica dorada con pan de oro | Brillante, tarnished en bordes |
| **Susurrante** | Piedra gris porosa | Superficie áspera, textura mineral |
| **Drakula** | Cuero oscuro envejecido | Arrugado, mate, desgastado en bordes |
| **Xavier** | Porcelana con óleo dorado | Pinceladas texturizadas, brillo irregular |
| **Greedy** | Jade verde tallado | Pulido, translúcido en bordes |
| **Informante** | Obsidiana negra | Brillante, reflejos especulares, cortante |
| **Germ** | Porcelana barata brillante | Esmalte de juguete, reflejos duros |
| **Business** | Metal pintado azul marino | Acero con pintura automotriz, rayones |
| **Lovers** | Dos maderas distintas unidas | Junta visible, vetas diferentes |
| **User** | **Madera tallada y pintada de rojo** | Laca brillante, como juguete artesanal |

---

## Prompts por voz

### 🎭 ALL — Short Prompts (Recraft/Vectr/etc.)

| Voz | Prompt |
|-----|--------|
| **Jane** | `realistic white porcelain half-face mask, aged with fine crackle lines, large hollow eye sockets revealing human-sized eyes inside that are solid white with black sclera staring forward, thin slightly crooked mouth slit showing depth, dramatic studio lighting, uncanny valley, transparent background` |
| **Doktor** | `realistic bone-colored polished wood half-face mask, visible wood grain, round empty wireframe glasses, inside the eye holes are solid bone-colored human eyes with dark grey sclera, frozen gentle smile slit, realistic mask texture, uncanny, transparent background` |
| **Conquest** | `realistic broken porcelain half-face mask, jagged crack from eye socket across cheek, inside the eye holes are solid white human eyes with black sclera filled with rage, tight clenched jaw slit, chipped edges, realistic, uncanny valley, transparent background` |
| **Narrador** | `realistic ceramic half-face mask with gold leaf trim slightly tarnished, large eye holes revealing solid gold-colored human eyes with black sclera, mouth frozen open in O shape showing darkness inside, theatrical but wrong, realistic mask, transparent background` |
| **Susurrante** | `realistic rough grey stone half-face mask, porous surface texture, asymmetrical eye holes one larger inside which are solid grey human eyes with dark grey sclera, jagged barely-open mouth slit, primitive unsettling feel, transparent background` |
| **Drakula** | `realistic aged dark red leather half-face mask, worn patina, narrow aristocratic eye slits revealing solid dark red human eyes with black sclera, thin cruel smirk slit showing depth inside, old leather texture, transparent background` |
| **Xavier** | `realistic white porcelain half-face mask with thick golden oil paint brushstrokes, one eye winking one open, inside both holes are solid white human eyes with dark grey sclera, crooked smile slit, paint texture visible, transparent background` |
| **Greedy** | `realistic carved green jade half-face mask, polished smooth with slight translucency, small close-set eye holes revealing solid green human eyes with black sclera, wide grin showing small pointed teeth inside, greedy expression, transparent background` |
| **Informante** | `realistic polished black obsidian half-face mask, sharp reflective surface, no mouth, horizontal slit for eyes revealing solid black human eyes with blacker sclera barely visible, featureless void, high contrast reflections, transparent background` |
| **Germ** | `realistic cheap glossy porcelain half-face mask, hard plastic-like shine, red rouge circles too high on cheeks, inside eye holes are solid white human eyes with black sclera, too-wide frozen smile, salesman vibes but wrong, transparent background` |
| **Business** | `realistic navy blue painted metal half-face mask, automotive paint with subtle scratches, rectangular eye holes revealing solid navy human eyes with black sclera, straight line mouth like ventriloquist dummy, cold metallic, transparent background` |
| **Lovers** | `realistic split half-face mask, left side bone wood right side pinkish wood joined by visible seam, two pairs of eye holes at different heights each revealing solid wood-colored eyes with dark sclera, one smile half one frown half, transparent background` |
| **User** | `realistic carved and lacquered red wooden half-face mask, glossy traditional craft finish, large round eye holes showing human-sized solid red eyes with black sclera staring forward, nutcracker hinged jaw slightly open revealing mechanical teeth inside, pink painted blush circles, deeply unsettling, transparent background` |

---

### 🎨 Detailed Prompts para LLM (generación directa de SVG)

*Estos prompts generan SVG con sombras, degradados, texturas sugeridas — para que las máscaras se vean como objetos reales.*

#### Jane — La dura (porcelana envejecida)

```
Generate a realistic SVG of a half-face mask made of aged porcelain.
The mask covers forehead to upper lip in a smooth curved shape.
MATERIAL: Bone white (#EDE8E2) with very subtle radial gradients suggesting rounded 3D volume. Fine crackle lines (tiny branching lines slightly darker #D4CFC9) across the surface suggesting age.
EYE HOLES: Large almond-shaped openings. Inside each hole, visible human-sized eyes: the eyeball is solid white (#EDE8E2, same as mask), the sclera (white of the eye) is dark grey (#2A2A2A). No visible pupil or iris — just a solid colored sphere with dark surround. The eyes stare directly forward, unblinking.
MOUTH: A thin horizontal slit, slightly crooked. The inside shows pure darkness (#000000) with subtle depth, not a flat shape — like an opening into nothing.
LIGHTING: Subtle highlights on the forehead and cheek areas suggesting a glossy porcelain finish. Drop shadow beneath the mask.
The mask should look like a real physical object — you can almost feel the smooth cold porcelain.
Transparent background. Viewbox: 0 0 200 200.
```

#### Doktor — El falso empático (madera pulida)

```
Generate a realistic SVG of a half-face mask made of polished bone-colored wood.
The mask covers forehead to upper lip in a softly rounded shape.
MATERIAL: Warm bone-cream (#F0E8D8) with subtle visible wood grain (thin slightly darker curved lines running vertically). Semi-matte finish with soft light reflection.
EYE HOLES: Round openings, slightly too large. Inside each hole, visible human-sized eyes: the eyeball is solid bone-cream (#F0E8D8), the sclera is dark charcoal (#2E2E2E). Dead, unblinking stare forward.
Around each eye: empty round wireframe glasses — thin dark metal circles (#3A3A3A) that catch light on their top edges. No lenses. Just frames floating in front of the hollow eyes.
MOUTH: Curved into a gentle U-shape, but frozen. The opening shows deep black (#000000) inside with subtle shadow suggesting the mouth continues back into darkness.
LIGHTING: Soft studio light from upper left, warm wood grain visible in the lighter areas.
The mask should look hand-carved from a single piece of wood, with visible tool marks and craftsmanship.
Transparent background. Viewbox: 0 0 200 200.
```

#### Conquest — El implacable roto (porcelana quebrada)

```
Generate a realistic SVG of a half-face mask made of pure white porcelain that is visibly cracked and damaged.
MATERIAL: Bright white (#FFFFFF) porcelain with glossy finish. One prominent jagged crack starts at the left eye socket and spiderwebs down across the cheek — the crack line is thin and dark (#333333) with tiny chips along the edges (small white missing pieces revealing darker shadow underneath).
EYE HOLES: Sharp triangular downward-pointing slits. Inside, visible human-sized eyes: solid white (#FFFFFF) eyeballs with pitch black (#000000) sclera. The eyes are wide, intense, filled with barely contained fury.
MOUTH: Tight straight frown, edges slightly jagged and chipped as if the porcelain is fracturing here too. Deep black (#000000) opening.
LIGHTING: Hard dramatic light creating high contrast — bright highlights on the forehead, deep shadows in the cracks and eye sockets.
The mask should feel like it's about to shatter completely. The cracks should look three-dimensional, like you could feel them with your fingers.
Transparent background. Viewbox: 0 0 200 200.
```

#### Narrador — El cuentacuentos (cerámica dorada)

```
Generate a realistic SVG of a half-face mask made of ceramic with gold leaf decoration.
MATERIAL: White ceramic (#F5F0E8) with thin gold leaf trim (#D4AF37) along the outer edge. The gold should show subtle tarnishing — slightly darker patches and uneven edges where the leaf has worn away.
EYE HOLES: Wide round openings, oversized and doll-like. Inside, visible human-sized eyes: solid gold-colored (#D4AF37) eyeballs with dark grey (#2A2A2A) sclera. The eyes are slightly too large to be human, staring wide.
MOUTH: Open in a wide O shape, like frozen narration or a silent scream. The inside is deep black (#000000) suggesting infinite darkness behind the mask.
LIGHTING: Theatrical spotlight from above — bright on the forehead, dramatic shadows in the eye sockets and mouth. The gold trim should catch light and shine.
The mask should feel like a cursed theater prop — beautiful from afar, wrong up close.
Transparent background. Viewbox: 0 0 200 200.
```

#### Susurrante — El violento susurro (piedra gris)

```
Generate a realistic SVG of a half-face mask carved from rough grey stone.
MATERIAL: Grey stone (#B8B4AC) with visible porous texture — tiny darker speckles and irregularities across the surface. The texture should look rough and unrefined, like primitive stonework, with subtle shadow in the pores.
EYE HOLES: Intentionally asymmetrical — left eye is a small round hole, right eye is larger and stretched downward in a misshapen oval. Inside both, visible human-sized eyes: solid grey stone-colored (#B8B4AC) eyeballs with very dark grey (#1A1A1A) sclera. The eyes don't align properly, adding to the wrongness.
MOUTH: A jagged barely-open horizontal slit, like the stone was chiseled open. Inside is pure black (#0A0A0A) with rough edges suggesting the opening was made by force.
LIGHTING: Harsh side lighting emphasizing the rough stone texture, casting deep shadows in the porous surface.
The mask should feel ancient, primitive, like something unearthed from a burial site.
Transparent background. Viewbox: 0 0 200 200.
```

#### Drakula — El vampiro (cuero envejecido)

```
Generate a realistic SVG of a half-face mask made of aged dark red leather.
MATERIAL: Dark burgundy leather (#5A0000) with visible wear — the surface shows subtle creasing, slightly lighter distressed areas at the edges, and a matte non-reflective finish. The leather has been shaped over a form, with slight asymmetry suggesting handcrafting.
EYE HOLES: Narrow sharp angled slits, aristocratic and cruel. Inside, visible human-sized eyes: solid dark red (#5A0000) eyeballs with black (#000000) sclera. The eyes are slightly narrowed, predatory, watching.
MOUTH: A thin cruel smirk — barely a line, one corner turned up just slightly, suggesting ancient amusement at mortal suffering. The slit shows blackness (#000000) within.
LIGHTING: Low dramatic light from below, casting shadows upward across the face — horror lighting. The leather texture should be visible as subtle surface variation.
The mask should feel old, expensive, and evil — like something passed down through a vampire family for centuries.
Transparent background. Viewbox: 0 0 200 200.
```

#### Xavier — El creativo arrogante (porcelana con óleo)

```
Generate a realistic SVG of a half-face mask with visible artistic modifications.
MATERIAL: White porcelain (#F5F0E8) base with thick golden oil paint (#D4AF37) applied in irregular brushstrokes on the right side. The paint strokes should have visible brush texture — thick ridges of paint catching light differently than the smooth porcelain. Some gold paint has dripped slightly.
EYE HOLES: Left eye is a normal almond slit. Inside, a solid white (#F5F0E8) eyeball with dark grey (#2A2A2A) sclera. Right eye is half-closed — the eyelid is drooped mid-blink, frozen. Inside the half-visible eye hole: same solid white eye with dark sclera, partially obscured by the drooping porcelain lid.
MOUTH: Asymmetrical smirk — left corner curved up, right corner straight. Deep black (#000000) opening.
LIGHTING: Bright art-studio light, making the glossy oil paint strokes pop against the matte porcelain.
The mask should look like a frustrated artist tried to "improve" a classic mask and made it wrong.
Transparent background. Viewbox: 0 0 200 200.
```

#### Greedy Grinner — El goblin avaro (jade tallado)

```
Generate a realistic SVG of a half-face mask carved from polished green jade.
MATERIAL: Rich jade green (#7B9E3A) with subtle translucency — the edges of the mask should catch light and glow slightly, suggesting the stone is thin enough to be semi-transparent. The surface is polished to a smooth glass-like finish with sharp visible reflections.
EYE HOLES: Small round beady openings, set closer together than human eyes would be. Inside, visible eyes: solid jade-green (#7B9E3A) eyeballs with black (#000000) sclera. The eyes are small and predatory.
MOUTH: A grotesquely wide grin, carved into the jade. Inside the grin: small pointed teeth, carved from the jade itself (same green), irregularly shaped like needles. Behind the teeth, pure black (#000000) depth.
CHIN: Carved to a sharp point, inhumanly narrow.
LIGHTING: Bright top light making the polished jade gleam, with green-tinted reflections on the curved surfaces.
The mask should look like a cursed artifact from a temple treasury — beautiful, precious, and wrong.
Transparent background. Viewbox: 0 0 200 200.
```

#### Informante — El misterioso (obsidiana negra)

```
Generate a realistic SVG of a half-face mask carved from polished black obsidian.
MATERIAL: Pure black obsidian (#1A1A20) with sharp specular reflections — the surface is glass-smooth and highly reflective, showing bright white highlight streaks across the curved forehead and cheek areas. The reflections should suggest a glossy volcanic glass surface.
EYE HOLES: No individual eye holes. Instead, a single continuous thin horizontal slot at eye level, like the slit of a sleeping doll. Inside this slot: barely visible, solid dark grey (#2A2A2A) eyeballs with blacker-than-black sclera — almost invisible against the obsidian, but just discernible as shapes moving in the darkness.
MOUTH: Completely absent. The lower half of the mask is a smooth continuous curve uninterrupted by any opening. The obsidian surface reflects light across where a mouth should be.
LIGHTING: Strong raking light from the side creating dramatic highlights that sweep across the curved obsidian surface, emphasizing every contour.
The mask should look like a void given form — beautiful, reflective, empty.
Transparent background. Viewbox: 0 0 200 200.
```

#### Germ — El vendedor carismático (porcelana barata)

```
Generate a realistic SVG of a half-face mask made of cheap shiny porcelain.
MATERIAL: Pallid white (#F5F0EC) with an unnaturally glossy finish — the kind of cheap high-gloss glaze found on mass-produced dolls. Hard bright reflections with no subtlety, revealing the cheap material underneath. The surface is too perfect and too shiny.
EYE HOLES: Smoothly arched openings with an exaggerated upward curve, like cartoon delight. Inside, visible human-sized eyes: solid white (#F5F0EC) eyeballs with black (#000000) sclera. The eyes are wide and unblinking.
CHEEKS: Two perfectly circular rouge spots, painted on with sharp edges — they don't blend into the skin, they sit ON TOP of the porcelain like stickers. Pink-red (#E8A0A0). Positioned too high, just below the eyes instead of on the apple of the cheek.
MOUTH: A wide smile frozen in an exaggerated arc, too wide for a human face. Deep black (#000000) inside.
LIGHTING: Harsh direct light creating sharp reflections on the cheap glossy surface.
The mask should look like a children's toy that has been watching you all night.
Transparent background. Viewbox: 0 0 200 200.
```

#### Business Man — El despiadado corporativo (metal pintado)

```
Generate a realistic SVG of a half-face mask made of painted metal.
MATERIAL: Steel base with dark navy blue automotive paint (#1B2A4A). The surface shows subtle metallic reflection — not a plastic shine but a true metal gleam. Subtle scratches in the paint reveal lighter metal underneath (thin bright lines #8899AA). The edges of the mask are raw metal, slightly worn.
EYE HOLES: Perfectly rectangular openings with sharp 90-degree corners, like a machine cut them. Inside, visible human-sized eyes: solid navy blue (#1B2A4A) eyeballs with very dark grey (#1A1A1A) sclera. The eyes are completely expressionless — just two cold spheres staring.
MOUTH: A single ruler-straight horizontal slit, cut with precision. The inside is pure black (#000000) with sharp clean edges.
LIGHTING: Cold overhead fluorescent lighting — flat, unflattering, corporate. Softer reflections than sunlight.
The mask should feel industrial, mass-produced, like something assembled on a factory line that processes human faces.
Transparent background. Viewbox: 0 0 200 200.
```

#### The Lovers — La voz dual (dos maderas)

```
Generate a realistic SVG of a half-face mask split vertically into two different woods joined together.
MATERIAL: Left half is pale bone-colored wood (#EDE8D8) with fine straight grain. Right half is pinkish-fleshtone wood (#E0C0C8) with visible knot patterns. The join is a visible jagged seam running vertically down the center — not a clean cut, but two halves forced together, with a thin dark gap (wood glue and shadow) visible between them.
EYE HOLES: Left side has one almond-shaped eye at normal height. Right side has one round eye hole positioned slightly lower. Each eye hole contains a visible human-sized eye: left eye is solid pale-wood-colored (#EDE8D8), right eye is solid pinkish-wood-colored (#E0C0C8), both with dark grey (#2A2A2A) sclera. The two pairs of eyes don't align — they look in slightly different directions.
MOUTH: Two half-mouths meeting at the center seam. Left half curves up in a crescent smile, right half curves down in a crescent frown. They don't connect properly at the center. Deep black (#000000) inside.
LIGHTING: Warm light from the front, showing the contrasting wood grains and the rough seam between them.
The mask should look like two people were carved into the same piece of wood and the join is where they were forced together.
Transparent background. Viewbox: 0 0 200 200.
```

#### User — El humano (madera laqueada — la más perturbadora)

```
Generate a realistic SVG of a half-face mask made of carved wood with red lacquer finish, traditional craft style.
MATERIAL: Solid wood carved into a half-face shape, coated with thick bright red lacquer (#CC2222). The surface is glossy and reflective like a traditional Asian lacquerware piece, with visible brush strokes in the finish and subtle unevenness revealing handcrafting. Small imperfections in the lacquer catch light.
EYE HOLES: Large round openings, generously sized so you can see deep inside. Within each opening, visible in clear detail: human-sized eyes. The eyeballs are the exact same red as the mask (#CC2222). The sclera (white of the eyes) is a sickly grey-black (#2A2A2A). No iris, no pupil — just solid red spheres with dark surrounds. The eyes stare directly forward, unblinking, creating the unmistakable impression that something is inside the mask looking out. The effect should be deeply unsettling — it looks like a person is wearing the mask, but the solid red eyes with black sclera prove it isn't human.
CHEEKS: Two perfectly round pink blush circles (#FF8888), painted on the lacquer surface with visible brush edges. They look artificial, applied separately, like a doll's makeup.
MOUTH: Nutcracker-style hinged jaw mechanism. Upper lip is a fixed horizontal line showing black (#000000) depth behind. The lower jaw is a separate piece — a half-circle of red lacquered wood, slightly separated from the upper mask by a visible gap (showing the mechanism inside, dark #1A1A1A). The jaw is slightly ajar — not fully open, not fully closed. Inside the mouth opening: the hint of mechanical teeth (small white irregular rectangles) in a row, like a wooden nutcracker doll. The gap between upper and lower jaw reveals the internal structure — dark shadow with subtle metallic hints of the hinge mechanism.
LIGHTING: Soft even light that brings out the deep gloss of the lacquer, with gentle highlights on the curved surfaces and inside the visible eye sockets.
This mask is the centerpiece of the collection — the most human-like and therefore the most disturbing. Everything about it says "person inside" except the eyes, which say "not human."
Transparent background. Viewbox: 0 0 200 200.
```

---

## Notas técnicas

- **Viewbox:** 0 0 200 200 (estándar, fácil de escalar)
- **Formato:** SVG con degradados radiales/lineales, sombras, y múltiples capas para dar profundidad
- **Paleta:** máximo 5 colores por máscara (máscara + ojos + sclera + boca + acento)
- **Los ojos son el elemento clave** — deben estar claramente dentro del hueco, visibles, con la esclerótica oscura que los delata como inhumanos
- **Compatibilidad:** Recraft.ai para los short prompts; LLMs con capacidad SVG para los detailed prompts
- **Overlay:** todas tienen borde oscuro sutil (#1A1A1A) para contraste sobre dark theme

---

## Referencias visuales

| Elemento | Inspiración |
|----------|-------------|
| Factor inquietante | Máscaras Noh reales — la sensación de que miran |
| Ojos dentro del hueco | Maniquíes con ojos realistas — el efecto uncanny |
| Material User | Máscaras de laca roja tradicional china/japonesa |
| Mandíbula User | Nutcracker clásico — madera, articulación visible |
| Material Jane/Doktor | Porcelana Ming — craqueladuras finas |
| Obsidiana Informante | Espejos de obsidiana azteca — reflejos cortantes |
| Jade Greedy | Tallados de jade chino — translucidez |
| Dos maderas Lovers | Ensambles japoneses — la junta visible |
| Cuero Drakula | Máscaras venecianas de cuero — uso y edad |
