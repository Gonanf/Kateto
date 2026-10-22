// jaw_mount.scad — Soporte para el servo de mandibula de la mascara Hannya
//
// =============================================================================
// MEDIDAS A VERIFICAR EN LA MASCARA REAL ANTES DE IMPRIMIR:
// 1. Distancia desde el eje de giro de la mandibula hasta el anclaje del eslabon
//    (determina el brazo de palanca mecanico y el recorrido angular necesario).
// 2. Curvatura y grosor de la resina interior del menton/mejilla donde asienta la base.
// 3. Espacio libre vertical (Z) para evitar que la bocina/horn del servo roce
//    con la cara del usuario o la pared interior de la mascara.
// 4. Diametro de los tornillos de fijacion a la mascara (M2.5 o M3 segun insertos).
// =============================================================================

include <params.scad>

module jaw_mount() {
    box_outer_l = servo_length + (wall_thickness * 2);
    box_outer_w = servo_width + (wall_thickness * 2);
    box_outer_h = servo_height;

    flange_ext_l = servo_flange_length + (wall_thickness * 2);
    base_l = flange_ext_l + 16.0; // Orejas adicionales para fijar a la mascara
    base_w = box_outer_w + 10.0;

    difference() {
        union() {
            // Placa base de fijacion a la mascara
            translate([-base_l / 2, -base_w / 2, 0])
                cube([base_l, base_w, base_thickness]);

            // Cuerpo del alojamiento del servo
            translate([-box_outer_l / 2, -box_outer_w / 2, base_thickness])
                cube([box_outer_l, box_outer_w, box_outer_h]);

            // Salientes superiores para atornillar las orejas del servo
            translate([-servo_flange_length / 2 - wall_thickness, -box_outer_w / 2, base_thickness + box_outer_h - 4.0])
                cube([servo_flange_length + (wall_thickness * 2), box_outer_w, 4.0]);
        }

        // Cavidad pasante para el cuerpo del servo
        translate([-servo_length / 2, -servo_width / 2, -1])
            cube([servo_length, servo_width, box_outer_h + base_thickness + 2]);

        // Ranura para paso de cable lateral del servo
        translate([-servo_length / 2 - 2, -4.0 / 2, base_thickness])
            cube([servo_length + 4, 4.0, 8.0]);

        // Agujeros para atornillar el servo a las orejas (M2 autorroscante)
        translate([-servo_hole_dist / 2, 0, base_thickness + box_outer_h - 10])
            cylinder(d = screw_m2_tap, h = 15);
        translate([servo_hole_dist / 2, 0, base_thickness + box_outer_h - 10])
            cylinder(d = screw_m2_tap, h = 15);

        // Agujeros de montaje de la base hacia la mascara (4 esquinas M3)
        translate([-base_l / 2 + 4.5, -base_w / 2 + 4.5, -1])
            cylinder(d = screw_m3_hole, h = base_thickness + 2);
        translate([base_l / 2 - 4.5, -base_w / 2 + 4.5, -1])
            cylinder(d = screw_m3_hole, h = base_thickness + 2);
        translate([-base_l / 2 + 4.5, base_w / 2 - 4.5, -1])
            cylinder(d = screw_m3_hole, h = base_thickness + 2);
        translate([base_l / 2 - 4.5, base_w / 2 - 4.5, -1])
            cylinder(d = screw_m3_hole, h = base_thickness + 2);
    }
}

// Renderizado directo
jaw_mount();
