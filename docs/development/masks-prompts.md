# Kateto Masks — SVG Generation Prompts

> Basado en: `concepts/avatars.md` — diseño de máscaras puppet-style, versión uncanny valley.
> Julio 2026.

---

## Concepto base

Todas las máscaras son **objetos físicos realistas** — se ven como máscaras de verdad hechas de porcelana, madera, cuero o metal. No son planas ni minimalistas. Tienen textura, profundidad, sombras, reflejos de luz.

**Silueta Noh — todas las máscaras:** La forma base de todas las máscaras está inspirada en **máscaras Noh** — alargada verticalmente, no un óvalo genérico. Las propiedades anatómicas (cuencas de ojos, pómulos, boca) **se expanden fuera del contorno base** en vez de estar contenidas dentro de una forma de huevo. La silueta tiene una frente que se ensancha, cuencas que protruyen, pómulos marcados que empujan el borde, y un mentón que se estrecha. No son caras humanas contenidas en un óvalo — cada máscara tiene una **forma facial esculpida** con regiones anatómicas distinguibles.

**Espectro estilístico:** Van desde caricatura con proporciones realistas (User) hasta realismo Noh tradicional (el resto). El denominador común es que **parecen objetos reales esculpidos** — no hay flat vector ni minimalismo.

- **Máscara User (la roja):** Caricatura Noh exagerada — forma alargada, propiedades expandiéndose fuera del contorno, cachetes abultados, mandíbula separable tipo cascanueces. **Ultra realismo solo en los ojos** — son fotorealistas para crear el contraste más perturbador.
- **Resto de máscaras:** Realismo Noh clásico — la misma silueta de máscara Noh con cuencas, pómulos y boca expandiéndose fuera del contorno, pero tratadas con proporciones más contenidas y realistas. Énfasis en textura de material y profundidad. Ojos de color sólido (sin hiperrealismo).

Las máscaras cubren **media cara** (frente a labio superior) y tienen **huecos para los ojos grandes**, pero no están vacíos: dentro de cada hueco se ven **ojos humanos**, del mismo color que la máscara, con la esclerótica (el blanco del ojo) negra o gris oscura. Parece que hay alguien adentro — pero sus ojos dejan claro que no es humano.

**Reglas del sistema visual:**
- **Silueta Noh estándar** — alargada, con cuencas, pómulos y mentón expandiéndose fuera del contorno oval. La User Mask es la única con tratamiento caricaturesco exagerado de esta silueta
- **Materiales:** porcelana, madera, cuero, metal, cerámica — según la voz
- **Ojos visibles dentro de los huecos** — ojos de tamaño humano, del mismo color que la máscara, con esclerótica negra/gris
- **Los ojos miran hacia adelante** — fijos, sin pestañear, como si la cosa dentro de la máscara estuviera observando
- **Sin iris ni pupila visibles** — solo el color sólido del ojo + esclerótica oscura (excepto User Mask, que igual no tiene iris/pupila pero es hiperrealista)
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
| **User** | **Madera tallada y pintada de rojo, forma Noh** | **Laca brillante, forma alargada con cuencas y cachetes salientes, mandíbula separable** |

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
| **User** | `carved wooden half-face mask with Noh proportions, elongated silhouette with protruding eye sockets and cheekbones, glossy red lacquer finish, large deep eye sockets revealing photorealistic human-sized solid red eyes with black sclera staring forward — the ONLY hyperrealistic element, nutcracker hinged jaw slightly open revealing mechanical teeth and brass mechanism inside, pink painted blush circles, semi-caricature style with realistic proportions, deeply unsettling, transparent background` |

---

### 🎨 Detailed Prompts para LLM (generación directa de SVG)

*Estos prompts generan SVG con sombras, degradados, texturas sugeridas — para que las máscaras se vean como objetos reales.*

#### Jane — La dura (porcelana envejecida)

```
Generate a realistic SVG of a half-face mask made of aged porcelain, with Noh mask proportions — elongated vertically, not a simple oval. The silhouette expands outward at the eye sockets and cheekbones, creating a face-shaped contour with distinct anatomical regions that push beyond the basic oval outline.
MATERIAL: Bone white (#EDE8E2) with very subtle radial gradients suggesting rounded 3D volume. Fine crackle lines (tiny branching lines slightly darker #D4CFC9) across the surface suggesting age. The porcelain has a satin gloss finish that catches light gently.
SHAPE: The mask widens at the temples, the cheekbones protrude slightly beyond the main contour, and the chin tapers to a narrow point. A subtle brow ridge creates depth above the deep eye sockets. The overall silhouette reads as a traditional Noh mask — elegant, elongated, with anatomical features expanding the boundaries.
EYE SOCKETS: Large almond-shaped cavities set deep into the mask. The brow ridge above them creates a pronounced overhang, casting the sockets in slight shadow. The outer edges of the sockets push outward beyond the main contour, giving the mask its distinctive Noh profile.
EYES: Inside each deep socket, visible human-sized eyes: the eyeball is solid white (#EDE8E2, same as mask), the sclera is dark grey (#2A2A2A). No visible pupil or iris — just a solid colored sphere with dark surround. The eyes stare directly forward, unblinking. The spherical volume of the eyes should be visible, catching light at their upper curve.
MOUTH: A thin horizontal slit, slightly crooked. The inside shows pure darkness (#000000) with subtle depth, not a flat shape — like an opening into nothing. The slit sits within the lower portion of the mask where the contour narrows toward the chin.
LIGHTING: Subtle highlights on the forehead and cheek areas suggesting a glossy porcelain finish. Drop shadow beneath the mask.
The mask should look like a real physical object — you can almost feel the smooth cold porcelain.
Transparent background. Viewbox: 0 0 200 200.
```

#### Doktor — El falso empático (madera pulida)

```
Generate a realistic SVG of a half-face mask made of polished bone-colored wood, with Noh mask proportions — elongated vertically, not a simple oval. The silhouette expands outward at the eye sockets and cheekbones, with the chin tapering to a narrow rounded point. The overall shape is a face-contoured Noh mask, not an oval.
MATERIAL: Warm bone-cream (#F0E8D8) with subtle visible wood grain (thin slightly darker curved lines running vertically following the elongated Noh silhouette). Semi-matte finish with soft light reflection.
SHAPE: The mask stretches vertically with a broad forehead that curves into pronounced brow ridges. The cheekbone area pushes outward slightly beyond the main contour, and the chin comes to a soft point. The eye sockets form deep hollows that are visible as convex bulges on the mask surface — the bone structure protrudes around them.
EYE SOCKETS: Round openings set deep into prominent surrounding bone. The area around each eye is raised — like the mask was carved to emphasize the orbital bone structure, pushing the socket outward. Inside each socket, visible human-sized eyes: the eyeball is solid bone-cream (#F0E8D8), the sclera is dark charcoal (#2E2E2E). Dead, unblinking stare forward.
Around each eye: empty round wireframe glasses — thin dark metal circles (#3A3A3A) that catch light on their top edges. No lenses. Just frames floating in front of the hollow eyes, resting on the protruding cheekbone area.
MOUTH: Curved into a gentle U-shape, but frozen — set within the narrowing lower portion of the mask. The opening shows deep black (#000000) inside with subtle shadow suggesting the mouth continues back into darkness.
LIGHTING: Soft studio light from upper left, warm wood grain visible in the lighter areas. Highlights catch the raised orbital bone area and the top rims of the glasses.
The mask should look hand-carved from a single piece of wood, with visible tool marks and craftsmanship following the Noh-inspired contours.
Transparent background. Viewbox: 0 0 200 200.
```

#### Conquest — El implacable roto (porcelana quebrada)

```
Generate a realistic SVG of a half-face mask made of pure white porcelain that is visibly cracked and damaged, with Noh mask proportions — elongated vertically, with the silhouette expanding outward at the eye sockets and cheekbones. The face-shaped contour pushes beyond the basic oval, giving it a traditional Noh mask structure that is now shattered.

MATERIAL: Bright white (#FFFFFF) porcelain with glossy finish. One prominent jagged crack starts at the left eye socket and spiderwebs down across the cheek — the crack line is thin and dark (#333333) with tiny chips along the edges (small white missing pieces revealing darker shadow underneath). Additional smaller cracks spider toward the edges of the mask, following the Noh contour lines.
SHAPE: The mask widens at the temples with a prominent brow ridge. The cheekbone area projects outward, and one side has been partially chipped away at the edge, exposing the broken cross-section of the porcelain. The eye sockets are sharp triangular depressions that push the surrounding mask surface into angular planes. The chin is intact but the right edge shows a clean break where a piece of the Noh silhouette has been lost.
EYE SOCKETS: Sharp triangular downward-pointing slits set into deep angular hollows. The bone structure around the eyes is fractured and sharp. Inside, visible human-sized eyes: solid white (#FFFFFF) eyeballs with pitch black (#000000) sclera. The eyes are wide, intense, filled with barely contained fury.
MOUTH: Tight straight frown, edges slightly jagged and chipped as if the porcelain is fracturing here too. Deep black (#000000) opening. The mouth area sits in the narrowing lower portion of the Noh silhouette.
LIGHTING: Hard dramatic light creating high contrast — bright highlights on the forehead, deep shadows in the cracks and eye sockets.
The mask should feel like it's about to shatter completely. The cracks should look three-dimensional, like you could feel them with your fingers.
Transparent background. Viewbox: 0 0 200 200.
```

#### Narrador — El cuentacuentos (cerámica dorada)

```
Generate a realistic SVG of a half-face mask made of ceramic with gold leaf decoration, with Noh mask proportions — elongated vertically, the silhouette pushing outward at the cheekbones and eye sockets. The face-contoured shape reads as a traditional theatrical Noh mask, fitting its narrator role.
MATERIAL: White ceramic (#F5F0E8) with thin gold leaf trim (#D4AF37) along the outer edge. The gold should show subtle tarnishing — slightly darker patches and uneven edges where the leaf has worn away. The ceramic has a smooth satin finish beneath the gold accents.
SHAPE: The mask is dramatically elongated with a high sweeping forehead, prominent brow ridges that arch theatrically, and cheekbones that flare outward before the chin narrows to a point. The eye sockets are pushed forward in convex bulges, creating deep hollows between them. The mouth area is set low in the narrowing chin section, positioned for its wide O opening.
EYE SOCKETS: Wide round openings, oversized and doll-like, set into sockets with pronounced protruding rims. The area around each eye is raised like a theatrical mask, pushing the boundary outward. Inside, visible human-sized eyes: solid gold-colored (#D4AF37) eyeballs with dark grey (#2A2A2A) sclera. The eyes are slightly too large to be human, staring wide.
MOUTH: Open in a wide O shape, like frozen narration or a silent scream — positioned at the lower narrowing of the Noh silhouette. The inside is deep black (#000000) suggesting infinite darkness behind the mask.
LIGHTING: Theatrical spotlight from above — bright on the forehead, dramatic shadows in the eye sockets and mouth. The gold trim should catch light and shine against the white ceramic.
The mask should feel like a cursed theater prop — beautiful from afar, wrong up close.
Transparent background. Viewbox: 0 0 200 200.
```

#### Susurrante — El violento susurro (piedra gris)

```
Generate a realistic SVG of a half-face mask carved from rough grey stone, with Noh mask proportions — elongated vertically with a face-contoured silhouette. The eye sockets and cheekbones push outward beyond the basic oval, giving it the shape of a primitive Noh mask carved from living rock.
MATERIAL: Grey stone (#B8B4AC) with visible porous texture — tiny darker speckles and irregularities across the surface. The texture should look rough and unrefined, like primitive stonework, with subtle shadow in the pores.
SHAPE: The mask follows the elongated Noh silhouette but in a crude, asymmetrical way — the forehead is broad and uneven, one cheekbone protrudes more than the other, and the chin is a rough point. The eye sockets are deeply carved hollows that push the surrounding stone into irregular bulges. The carving looks intentional but brutal — like an ancient Noh mask hacked from stone.
EYE SOCKETS: Intentionally asymmetrical — left socket is a small round depression, right socket is larger and stretched downward in a misshapen oval. Both are carved deep into the stone with raised irregular rims. Inside both, visible human-sized eyes: solid grey stone-colored (#B8B4AC) eyeballs with very dark grey (#1A1A1A) sclera. The eyes don't align properly, adding to the wrongness.
MOUTH: A jagged barely-open horizontal slit, like the stone was chiseled open — positioned in the narrowing lower section. Inside is pure black (#0A0A0A) with rough edges suggesting the opening was made by force.
LIGHTING: Harsh side lighting emphasizing the rough stone texture, casting deep shadows in the porous surface.
The mask should feel ancient, primitive, like something unearthed from a burial site.
Transparent background. Viewbox: 0 0 200 200.
```

#### Drakula — El vampiro (cuero envejecido)

```
Generate a realistic SVG of a half-face mask made of aged dark red leather, shaped over a Noh mask form — elongated vertically, with the silhouette expanding at the cheekbones and narrowing to a pointed chin. The leather follows the face-contoured shape of a traditional Noh mask.
MATERIAL: Dark burgundy leather (#5A0000) with visible wear — the surface shows subtle creasing, slightly lighter distressed areas at the edges, and a matte non-reflective finish. The leather has been shaped over a Noh mask mold, with slight asymmetry suggesting age and use.
SHAPE: The mask follows classic Noh proportions — a broad forehead that tapers to a prominent brow ridge, cheekbones that flare outward (accentuated by the leather stretching over them), and a sharply narrowing chin. The leather conforms to the protruding eye socket structure, with visible wrinkles at the corners where the material bunches.
EYE SOCKETS: Narrow sharp angled slits set into sockets with raised leather surrounding them — the bone structure beneath the leather pushes outward, creating convex bulges around the eye openings. Inside, visible human-sized eyes: solid dark red (#5A0000) eyeballs with black (#000000) sclera. The eyes are slightly narrowed, predatory, watching.
MOUTH: A thin cruel smirk — barely a line, one corner turned up just slightly, suggesting ancient amusement at mortal suffering. The slit shows blackness (#000000) within. Positioned where the Noh silhouette narrows.
LIGHTING: Low dramatic light from below, casting shadows upward across the face — horror lighting. The leather texture should be visible as subtle surface variation.
The mask should feel old, expensive, and evil — like something passed down through a vampire family for centuries.
Transparent background. Viewbox: 0 0 200 200.
```

#### Xavier — El creativo arrogante (porcelana con óleo)

```
Generate a realistic SVG of a half-face mask with Noh mask proportions — elongated vertically, with the silhouette expanding outward at the cheekbones and eye sockets. The face-contoured shape shows visible artistic modifications to a traditional Noh mask form.
MATERIAL: White porcelain (#F5F0E8) base with thick golden oil paint (#D4AF37) applied in irregular brushstrokes on the right side. The paint strokes should have visible brush texture — thick ridges of paint catching light differently than the smooth porcelain. Some gold paint has dripped slightly. The Noh silhouette is partially obscured by the paint application.
SHAPE: The Noh shape is still legible beneath the paint — broad forehead, protruding eye socket area, cheekbones that push outward, and a narrowing chin. The golden paint application follows the contours of the mask, with thicker buildup in the concave areas (eye sockets) and thinner application on the convex surfaces (cheekbones).
EYE SOCKETS: Left eye socket is a normal almond-shaped depression in the Noh style, with raised orbital bone structure surrounding it. Inside, a solid white (#F5F0E8) eyeball with dark grey (#2A2A2A) sclera. Right eye socket is half-obscured — the eyelid is drooped mid-blink, frozen, with gold paint drips crossing the boundary. Inside the half-visible eye hole: same solid white eye with dark sclera, partially obscured by the drooping porcelain lid and paint.
MOUTH: Asymmetrical smirk — left corner curved up, right corner straight. Deep black (#000000) opening. Set in the narrowing lower portion of the mask.
LIGHTING: Bright art-studio light, making the glossy oil paint strokes pop against the matte porcelain.
The mask should look like a frustrated artist tried to "improve" a classic Noh mask and made it wrong.
Transparent background. Viewbox: 0 0 200 200.
```

#### Greedy Grinner — El goblin avaro (jade tallado)

```
Generate a realistic SVG of a half-face mask carved from polished green jade, with Noh mask proportions — elongated vertically, the silhouette expanding outward at exaggerated cheekbones and a sharply narrowing chin. The jade follows a traditional Noh mask form but with goblin-like distortions.
MATERIAL: Rich jade green (#7B9E3A) with subtle translucency — the edges of the mask should catch light and glow slightly, suggesting the stone is thin enough to be semi-transparent. The surface is polished to a smooth glass-like finish with sharp visible reflections.
SHAPE: Exaggerated Noh proportions — a broad flat forehead, massive protruding cheekbones that flare outward dramatically, deep eye sockets that push the surrounding jade into angular planes, and a chin carved to an inhumanly sharp point. The silhouette looks like a Noh mask caricatured by a greedy spirit.
EYE SOCKETS: Small round beady openings set close together, deep within prominent protruding eye sockets. The raised bone structure around the eyes is exaggerated, forming sharp ridges. Inside, visible eyes: solid jade-green (#7B9E3A) eyeballs with black (#000000) sclera. The eyes are small and predatory.
MOUTH: A grotesquely wide grin carved into the jade, stretching beyond the normal bounds of the Noh silhouette. Inside the grin: small pointed teeth, carved from the jade itself (same green), irregularly shaped like needles. Behind the teeth, pure black (#000000) depth. The grin sits low in the sharply narrowing chin section.
LIGHTING: Bright top light making the polished jade gleam, with green-tinted reflections on the curved surfaces.
The mask should look like a cursed artifact from a temple treasury — beautiful, precious, and wrong.
Transparent background. Viewbox: 0 0 200 200.
```

#### Informante — El misterioso (obsidiana negra)

```
Generate a realistic SVG of a half-face mask carved from polished black obsidian, with Noh mask proportions — elongated vertically, the silhouette widening at the temples and narrowing to a smooth point at the chin. The dark volcanic glass follows a traditional Noh mask contour.
MATERIAL: Pure black obsidian (#1A1A20) with sharp specular reflections — the surface is glass-smooth and highly reflective, showing bright white highlight streaks across the curved forehead and cheek areas. The reflections should suggest a glossy volcanic glass surface.
SHAPE: The mask follows a classic Noh silhouette — broad at the forehead, subtle outward curve at the cheekbone level, and a smooth taper to a rounded point at the chin. The surface is completely smooth with no anatomical protrusions — the obsidian has been polished to erase all facial features except the eye slot, creating a void-like Noh mask.
EYE SOCKETS: No individual eye holes. Instead, a single continuous thin horizontal slot at eye level, like the slit of a sleeping doll — cutting across the widest point of the Noh silhouette. Inside this slot: barely visible, solid dark grey (#2A2A2A) eyeballs with blacker-than-black sclera — almost invisible against the obsidian, but just discernible as shapes moving in the darkness.
MOUTH: Completely absent. The lower half of the mask is a smooth continuous curve uninterrupted by any opening — following the Noh taper to the chin. The obsidian surface reflects light across where a mouth should be.
LIGHTING: Strong raking light from the side creating dramatic highlights that sweep across the curved obsidian surface, emphasizing every contour of the Noh silhouette.
The mask should look like a void given form — beautiful, reflective, empty.
Transparent background. Viewbox: 0 0 200 200.
```

#### Germ — El vendedor carismático (porcelana barata)

```
Generate a realistic SVG of a half-face mask made of cheap shiny porcelain, with Noh mask proportions — elongated vertically, the silhouette following the classic Noh contour with broad forehead, protruding cheekbone area, and narrow chin. The cheap materials betray the elegant form.
MATERIAL: Pallid white (#F5F0EC) with an unnaturally glossy finish — the kind of cheap high-gloss glaze found on mass-produced dolls. Hard bright reflections with no subtlety, revealing the cheap material underneath. The surface is too perfect and too shiny, coating an otherwise graceful Noh silhouette.
SHAPE: The Noh silhouette is there but executed poorly — the forehead width is slightly off, the cheekbone protrusion is asymmetrical, and the chin point is blunted. It's like someone tried to mass-produce a Noh mask and got the proportions wrong. The eye sockets bulge outward unnaturally, and the painted-on features don't align with the mask topography.
EYE SOCKETS: Smoothly arched openings with an exaggerated upward curve, like cartoon delight — set into cheap bulging sockets that push the surrounding porcelain outward. Inside, visible human-sized eyes: solid white (#F5F0EC) eyeballs with black (#000000) sclera. The eyes are wide and unblinking.
CHEEKS: Two perfectly circular rouge spots, painted on with sharp edges — they don't blend into the skin, they sit ON TOP of the porcelain like stickers. Pink-red (#E8A0A0). Positioned too high, just below the eyes instead of on the apple of the cheek, sitting on the protruding cheekbone area.
MOUTH: A wide smile frozen in an exaggerated arc, too wide for a human face — stretching across the lower portion of the Noh silhouette. Deep black (#000000) inside.
LIGHTING: Harsh direct light creating sharp reflections on the cheap glossy surface.
The mask should look like a children's toy that has been watching you all night.
Transparent background. Viewbox: 0 0 200 200.
```

#### Business Man — El despiadado corporativo (metal pintado)

```
Generate a realistic SVG of a half-face mask made of painted metal, shaped with Noh mask proportions — elongated vertically, with the silhouette expanding at the cheekbones and tapering to a narrow chin. The cold industrial metal betrays the traditional Noh form.
MATERIAL: Steel base with dark navy blue automotive paint (#1B2A4A). The surface shows subtle metallic reflection — not a plastic shine but a true metal gleam. Subtle scratches in the paint reveal lighter metal underneath (thin bright lines #8899AA). The edges of the mask are raw metal, slightly worn. The Noh silhouette is executed with cold industrial precision.
SHAPE: The Noh shape is machine-perfect — symmetrical forehead, exactly matched cheekbone protrusions on both sides, precisely machined chin taper. The eye sockets have been CNC-cut with geometric precision into the traditional Noh form. The result is a Noh mask that feels factory-made, not hand-carved.
EYE SOCKETS: Perfectly rectangular openings with sharp 90-degree corners, like a machine cut them — set into the precise Noh contour. Inside, visible human-sized eyes: solid navy blue (#1B2A4A) eyeballs with very dark grey (#1A1A1A) sclera. The eyes are completely expressionless — just two cold spheres staring.
MOUTH: A single ruler-straight horizontal slit, cut with precision across the lower section of the Noh silhouette. The inside is pure black (#000000) with sharp clean edges.
LIGHTING: Cold overhead fluorescent lighting — flat, unflattering, corporate. Softer reflections than sunlight.
The mask should feel industrial, mass-produced, like something assembled on a factory line that processes human faces.
Transparent background. Viewbox: 0 0 200 200.
```

#### The Lovers — La voz dual (dos maderas)

```
Generate a realistic SVG of a half-face mask split vertically into two different woods joined together, with Noh mask proportions — elongated vertically, the silhouette following the classic Noh contour but executed in two conflicting wood types.
MATERIAL: Left half is pale bone-colored wood (#EDE8D8) with fine straight grain. Right half is pinkish-fleshtone wood (#E0C0C8) with visible knot patterns. The join is a visible jagged seam running vertically down the center of the Noh shape — not a clean cut, but two halves forced together, with a thin dark gap (wood glue and shadow) visible between them.
SHAPE: The Noh silhouette is present but clearly assembled from two pieces — the left half has a slightly different forehead curve than the right, and the chin point is uneven where the two woods meet. The cheekbone protrusions are asymmetrical — left is more pronounced, right is flatter. The eye sockets sit at different levels because the two halves were carved separately.
EYE SOCKETS: Left side has one almond-shaped eye socket at normal height with a raised orbital rim. Right side has one round eye socket positioned slightly lower, with a flatter surrounding bone structure. Each eye socket contains a visible human-sized eye: left eye is solid pale-wood-colored (#EDE8D8), right eye is solid pinkish-wood-colored (#E0C0C8), both with dark grey (#2A2A2A) sclera. The two pairs of eyes don't align — they look in slightly different directions.
MOUTH: Two half-mouths meeting at the center seam. Left half curves up in a crescent smile, right half curves down in a crescent frown. They don't connect properly at the center of the Noh shape. Deep black (#000000) inside.
LIGHTING: Warm light from the front, showing the contrasting wood grains and the rough seam between them.
The mask should look like two people were carved into the same Noh mask and the join is where they were forced together.
Transparent background. Viewbox: 0 0 200 200.
```

#### User — El humano (madera laqueada — la más perturbadora)

> **Estilo:** Caricatura con proporciones realistas. La máscara tiene una **forma de máscara Noh** — alargada, no un óvalo genérico. Las propiedades anatómicas (cuencas de ojos, cachetes, boca) **se expanden fuera del contorno base** en vez de estar contenidas dentro de un óvalo. El **único ultra realismo** está en los ojos — deben ser hiperrealistas, como ojos humanos reales pero con color sólido y esclerótica oscura.

```
Generate an SVG of a half-face mask with Noh mask proportions — elongated vertically, not a simple oval.
The mask silhouette expands outward at the eye sockets (protruding cheekbone area), the cheeks puff out slightly beyond the main contour, and the hinged jaw / mouth area extends forward and downward as a separate piece. The overall shape reads as a stylized Noh mask with exaggerated anatomical features pushing the boundaries.

STYLE: Semi-caricature with realistic proportions. Think traditional Noh mask silhouette but with bolder features — prominent brow ridge, pronounced cheekbones that push the mask edge outward, a strong chin that tapers to a point. The mask doesn't just sit inside an oval; it HAS a face-shaped contour with distinct anatomical regions.

MATERIAL: Solid wood carved into a half-face shape, coated with thick bright red lacquer (#CC2222). Glossy and reflective like traditional Asian lacquerware, with visible brush strokes in the finish and subtle unevenness revealing handcrafting. Small imperfections in the lacquer catch light. The carved wood texture is visible only at the edges where lacquer has worn thin.

EYE SOCKETS: Two deep, prominent cavities that protrude outward from the mask surface — the bone structure around the eyes is exaggerated, creating visible convex bulges around the eye openings (like the raised brow and cheekbone of a Noh mask). The sockets themselves are large rounded triangles with the wide end at the outer corner, giving a slightly fox-like or mystical shape.

EYES (ULTRA REALISTIC — the only hyperrealistic element): Inside the deep sockets, human-sized eyes rendered with photorealistic detail. The eyeball is a perfect glossy sphere with subtle 3D curvature — you can see the spherical volume catching light. It is solid crimson red (#CC2222), the exact shade of the mask. The sclera (white of the eye) is a sickly dark grey-black (#1A1A1A). No visible iris or pupil — just a solid red orb with dark surround. BUT the rendering must be indistinguishable from a photograph: the wet reflection on the corneal surface, the subtle shadow where the eye sits in the socket, the spherical highlight that moves as if the eye is rotated. These eyes should look like actual human eyes that have been recolored — every fiber of realism except the impossible color and missing iris. The contrast between the stylized/caricature mask and these photoreal eyes is what makes it truly disturbing.

CHEEKS: Two perfectly round pink blush circles (#FF8888), painted on the lacquer surface with visible brush edges where the paint has slightly beaded up on the glossy lacquer. They sit prominently on the protruding cheek area, like doll makeup applied by hand — artificial, too perfect, positioned too high on the cheeks. These are part of the caricature style.

MOUTH: Nutcracker-style hinged jaw mechanism that extends outward from the mask as a separate physical piece. The upper lip is a fixed horizontal line embedded in the mask — a straight cut showing black (#000000) depth behind. The lower jaw is a detached piece: a half-oval of red lacquered wood suspended below the upper mask, separated by a visible gap of about 2-3mm. Through this gap: the internal mechanism is visible — dark shadows (#1A1A1A) with subtle metallic hints where brass pins and springs catch the light. The jaw is slightly ajar. Inside the mouth opening, visible: a row of small irregular white rectangular teeth (mechanical, carved from bone or wood) that sit along the upper jaw like a classic nutcracker doll. The lower half-circle seems to weigh heavy, like it could snap shut at any moment.

LIGHTING: Soft even studio light from upper left. The light creates gentle specular highlights on the glossy lacquer curves, catches the photorealistic wet reflection of the eyes, and casts subtle shadows in the deep eye sockets and the jaw mechanism gap. The red lacquer glows slightly warm in the light.

OVERALL CONCEPT: The mask is the centerpiece of the collection. It's designed as a Noh mask reimagined as a wooden nutcracker doll — then animated by something using it as a vessel. The caricature shape (exaggerated Noh proportions, protruding features, painted blush, hinged jaw) makes it read as "artificial" and "character-like." The photorealistic eyes floating inside the deep sockets contradict everything — they are windows to something real staring back at you, and that discrepancy is what makes it the most disturbing mask in the collection.

Transparent background. Viewbox: 0 0 200 200.
```

---

## Notas técnicas

- **Viewbox:** 0 0 200 200 (estándar, fácil de escalar)
- **Formato:** SVG con degradados radiales/lineales, sombras, y múltiples capas para dar profundidad
- **Paleta:** máximo 5 colores por máscara (máscara + ojos + sclera + boca + acento)
- **Los ojos son el elemento clave** — deben estar claramente dentro del hueco, visibles, con la esclerótica oscura que los delata como inhumanos
- **Silueta Noh universal:** todas las máscaras comparten la silueta Noh alargada con cuencas, pómulos y mentón expandiéndose fuera del contorno. Esto unifica el set visualmente
- **Espectro estilístico:** todas comparten la forma Noh. La User Mask es la única en caricatura Noh exagerada con ojos hiperrealistas. El resto son realismo Noh clásico con ojos de color sólido. El contraste estilístico entre User y resto refuerza el uncanny valley
- **Los ojos de la User Mask deben renderizarse con calidad hiperrealista** — refracción corneal, brillo esférico, profundidad de socket. Que duela lo real que se vean comparado con el resto del diseño caricaturesco
- **Compatibilidad:** Recraft.ai para los short prompts; LLMs con capacidad SVG para los detailed prompts
- **Overlay:** todas tienen borde oscuro sutil (#1A1A1A) para contraste sobre dark theme

---

## Referencias visuales

| Elemento | Inspiración |
|----------|-------------|
| Silueta base (todas) | Máscaras Noh reales — forma alargada, cuencas y pómulos expandiéndose fuera del contorno |
| Factor inquietante | Máscaras Noh reales — la sensación de que miran, el "entreabierto" de los ojos |
| Ojos dentro del hueco | Maniquíes con ojos realistas — el efecto uncanny |
| Material User | Máscaras de laca roja tradicional china/japonesa |
| Mandíbula User | Nutcracker clásico — madera, articulación visible |
| Material Jane/Doktor | Porcelana Ming — craqueladuras finas |
| Obsidiana Informante | Espejos de obsidiana azteca — reflejos cortantes |
| Jade Greedy | Tallados de jade chino — translucidez |
| Dos maderas Lovers | Ensambles japoneses — la junta visible |
| Cuero Drakula | Máscaras venecianas de cuero — uso y edad |
