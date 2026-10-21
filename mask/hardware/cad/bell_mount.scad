// bell_mount.scad — Soporte para solenoide percutor y campana de la mascara Hannya
//
// =============================================================================
// MEDIDAS A VERIFICAR EN LA MASCARA REAL ANTES DE IMPRIMIR:
// 1. Diametro y labio de la campana / cuenco metalico resonador utilizado.
// 2. Carrera util del solenoide (4 a 6 mm) y distancia de separacion al cuenco
//    (debe quedar 1 a 2 mm de espacio en reposo para permitir resonancia libre).
// 3. Espacio volumetrico en el interior de la frente o base de los cuernos de la mascara.
// 4. Espesor de pared para evitar transmitir vibracion sorda a la estructura.
// =============================================================================

include <params.scad>

module bell_mount() {
    cradle_l = solenoid_length + (wall_thickness * 2);
    cradle_w = solenoid_width + (wall_thickness * 2);
    cradle_h = solenoid_height + base_thickness;

    arm_length = 32.0;
    post_dia = 8.0;

    difference() {
        union() {
            // Cuna base para el solenoide
            translate([-cradle_l / 2, -cradle_w / 2, 0])
                cube([cradle_l, cradle_w, cradle_h]);

            // Brazo soporte saliente para montar el cuenco / campana
            translate([cradle_l / 2 - wall_thickness, -cradle_w / 2, 0])
                cube([arm_length, cradle_w, base_thickness + 2.0]);

            // Poste cilindrico para fijar el centro de la campana
            translate([cradle_l / 2 + arm_length - 8.0, 0, 0])
                cylinder(d = post_dia, h = bell_height + 4.0);

            // Orejas de fijacion a la mascara
            translate([-cradle_l / 2 - 8.0, -cradle_w / 2, 0])
                cube([8.0, cradle_w, base_thickness]);
        }

        // Alojamiento del cuerpo del solenoide
        translate([-solenoid_length / 2, -solenoid_width / 2, base_thickness])
            cube([solenoid_length, solenoid_width, solenoid_height + 5]);

        // Abertura frontal para el recorrido del percutor
        translate([solenoid_length / 2 - 2, -solenoid_width / 2 + 1, base_thickness + 2])
            cube([wall_thickness + 4, solenoid_width - 2, solenoid_height]);

        // Agujeros laterales para fijar el solenoide con tornillos M3
        translate([0, -cradle_w / 2 - 1, base_thickness + (solenoid_height / 2)])
            rotate([-90, 0, 0])
            cylinder(d = screw_m3_hole, h = cradle_w + 2);

        // Agujero roscado en poste de campana (tornillo axial M3)
        translate([cradle_l / 2 + arm_length - 8.0, 0, base_thickness])
            cylinder(d = screw_m3_tap, h = bell_height + 10);

        // Agujeros de anclaje a la mascara (M3)
        translate([-cradle_l / 2 - 4.0, 0, -1])
            cylinder(d = screw_m3_hole, h = base_thickness + 2);
        translate([cradle_l / 2 + arm_length - 4.0, 0, -1])
            cylinder(d = screw_m3_hole, h = base_thickness + 2);
    }
}

// Renderizado directo
bell_mount();
