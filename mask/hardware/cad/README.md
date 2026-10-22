# Modelos CAD Parametricos — MASK-7

Modelos OpenSCAD para los soportes y mecanismos de los actuadores fisicos de la mascara Hannya.

## Que Medir en la Mascara Fisica Real (5 Items Concretos)

Antes de imprimir los soportes, verifique con calibre (pie de rey) las siguientes 5 cotas clave en su mascara y ajuste `params.scad`:

1. **Distancia Interpupilar (IPD):** Mida la distancia de centro a centro entre las dos aberturas oculares de la mascara (rango habitual: 60 - 66 mm).
2. **Profundidad de Cuencas Oculares:** Espacio libre entre la cara interna de los orificios oculares de la mascara y la cara/ojos del usuario (minimo recomendado: 28 mm para permitir el mecanismo pan/tilt).
3. **Longitud del Brazo de Mandibula:** Distancia entre el pivote (bisagra) de la mandibula inferior y el punto de conexion del tirante (biela) del servo. Determina la relacion de palanca y torque efectivo.
4. **Espesor de Pared Interior para Inserciones:** Grosor de la cascara de la mascara en los puntos de apoyo del menton y frente para seleccionar la longitud adecuada de los tornillos o insertos termicos M3 sin perforar hacia el exterior.
5. **Diametro y Labio de Campana:** Diametro exterior del cuenco resonador y distancia de reposo al percutor del solenoide (debe haber entre 1.0 y 2.0 mm de holgura para no ahogar el sonido al golpear).

---

## Parametros de Impresion 3D Recomendados

Para garantizar resistencia mecanica frente a la fatiga ciclica de los servos y estabilidad termica ante el calor generado por los motores:

- **Material:** **PETG** (o ABS/ASA). Evitar PLA standard debido a la deformacion bajo carga prolongada y temperatura del ESP32/motores.
- **Altura de capa:** `0.20 mm`
- **Perimetros / Paredes:** `4 paredes` minimas (aprox. 1.6 mm de grosor solido perimetral).
- **Relleno (Infill):** `30%` (patron Gyroid o Cubic para resistencia isotropica).
- **Capas superiores e inferiores:** 5 solidas arriba y abajo.
- **Soportes:** Opcionales / minimos segun orientacion (los modelos estan disenados para imprimirse planos apoyados sobre la base).

---

## Generacion de Archivos STL

> **Nota:** En este entorno de desarrollo no se encuentra instalado el binario de OpenSCAD. La generacion de los archivos STL para corte (slicing) se realiza del lado del usuario mediante:

```bash
mkdir -p out

# Generar STL para soporte de mandibula:
openscad -o out/jaw_mount.stl mask/hardware/cad/jaw_mount.scad

# Generar STL para soporte de ojos (pan/tilt):
openscad -o out/eye_mount.stl mask/hardware/cad/eye_mount.scad

# Generar STL para soporte de campana:
openscad -o out/bell_mount.stl mask/hardware/cad/bell_mount.scad
```
