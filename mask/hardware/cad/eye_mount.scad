// eye_mount.scad — Soporte para servos de ojos (Pan / Tilt) de la mascara Hannya
//
// =============================================================================
// MEDIDAS A VERIFICAR EN LA MASCARA REAL ANTES DE IMPRIMIR:
// 1. Distancia interpupilar (IPD) entre los centros de las cuencas oculares de la mascara.
// 2. Profundidad disponible desde el plano de los parpados hasta la frente del usuario.
// 3. Radio maximo de los globos oculares acoplados para evitar colision en pan/tilt extremo.
// 4. Inclinacion del puente nasal interior donde apoya el soporte central.
// =============================================================================

include <params.scad>

module eye_mount() {
    pocket_l = servo_length;
    pocket_w = servo_width;
    pocket_h = servo_height;

    // Espacio para 2 servos (pan X y tilt Y) dispuestos en soporte integrado
    block_w = (pocket_w * 2) + (wall_thickness * 3);
    block_l = pocket_l + (wall_thickness * 2);
    block_h = pocket_h + base_thickness;

    flange_ext = 14.0;
    total_l = block_l + flange_ext;

    difference() {
        union() {
            // Cuerpo principal del bloque
            translate([-total_l / 2, -block_w / 2, 0])
                cube([total_l, block_w, block_h]);

            // Refuerzos laterales
            translate([-total_l / 2, -block_w / 2, 0])
                cube([total_l, wall_thickness, block_h + 3.0]);
            translate([-total_l / 2, block_w / 2 - wall_thickness, 0])
                cube([total_l, wall_thickness, block_h + 3.0]);
        }

        // Cavidad para Servo 1 (Eye X - Pan)
        translate([-pocket_l / 2, -pocket_w - (wall_thickness / 2), base_thickness])
            cube([pocket_l, pocket_w, pocket_h + 5]);

        // Cavidad para Servo 2 (Eye Y - Tilt)
        translate([-pocket_l / 2, (wall_thickness / 2), base_thickness])
            cube([pocket_l, pocket_w, pocket_h + 5]);

        // Ranura para cables en la base
        translate([-pocket_l / 2 - 2, -block_w / 2 + wall_thickness, base_thickness])
            cube([pocket_l + 4, block_w - (wall_thickness * 2), 4.0]);

        // Agujeros para orejas de servos (M2)
        // Servo 1
        translate([-servo_hole_dist / 2, -pocket_w / 2 - (wall_thickness / 2), base_thickness])
            cylinder(d = screw_m2_tap, h = block_h);
        translate([servo_hole_dist / 2, -pocket_w / 2 - (wall_thickness / 2), base_thickness])
            cylinder(d = screw_m2_tap, h = block_h);

        // Servo 2
        translate([-servo_hole_dist / 2, pocket_w / 2 + (wall_thickness / 2), base_thickness])
            cylinder(d = screw_m2_tap, h = block_h);
        translate([servo_hole_dist / 2, pocket_w / 2 + (wall_thickness / 2), base_thickness])
            cylinder(d = screw_m2_tap, h = block_h);

        // Agujeros de anclaje a la mascara (M3 conicas/pasantes en extremos)
        translate([-total_l / 2 + 3.5, 0, -1])
            cylinder(d = screw_m3_hole, h = block_h + 2);
        translate([total_l / 2 - 3.5, 0, -1])
            cylinder(d = screw_m3_hole, h = block_h + 2);
    }
}

// Renderizado directo
eye_mount();
