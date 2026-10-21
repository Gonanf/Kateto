// params.scad — Parametros globales para el montaje de actuadores MASK-7
// Compatible con OpenSCAD 2021+

$fn = 40; // Calidad de curvas circulares

// --- Tolerancia general para impresion FDM ---
tol = 0.35; // Holgura lateral para ajuste deslizante firme

// --- Micro-servo standard tipo MG90S / SG90 ---
servo_length = 22.8 + tol;       // Largo del cuerpo principal (mm)
servo_width  = 12.2 + tol;       // Ancho del cuerpo principal (mm)
servo_height = 22.5;             // Altura del cuerpo hasta las orejas de montaje (mm)
servo_total_height = 28.5;       // Altura total incluyendo cabezal del eje (mm)

servo_flange_length = 32.5;      // Largo total con orejas de fijacion (mm)
servo_flange_thickness = 2.5;    // Espesor de las orejas del servo (mm)
servo_hole_dist = 28.0;          // Distancia entre centros de tornillos de fijacion (mm)

// --- Tornilleria ---
screw_m2_dia = 2.0;              // Diametro nominal tornillo M2 (mm)
screw_m2_hole = 2.4;             // Agujero de paso M2 con holgura (mm)
screw_m2_tap  = 1.8;             // Agujero para autorroscar M2 en plastico (mm)

screw_m3_dia = 3.0;              // Diametro nominal tornillo M3 (mm)
screw_m3_hole = 3.4;             // Agujero de paso M3 con holgura (mm)
screw_m3_tap  = 2.8;             // Agujero autorroscante M3 (mm)

// --- Espesores estructurales de soportes ---
wall_thickness = 2.5;            // Espesor de pared minima para rigidez (mm)
base_thickness = 3.0;            // Espesor de la placa base atornillable (mm)

// --- Solenoide mini 5V (tipo JF-0530B) ---
solenoid_length = 30.0 + tol;    // Largo del cuerpo del solenoide (mm)
solenoid_width  = 13.0 + tol;    // Ancho del cuerpo del solenoide (mm)
solenoid_height = 15.0 + tol;    // Altura del cuerpo del solenoide (mm)
solenoid_hole_dist = 16.0;       // Distancia entre agujeros roscados M3 de fijacion (mm)

// --- Campana resonadora ---
bell_diameter = 40.0;            // Diametro de campana o cuenco (mm)
bell_height   = 20.0;            // Altura de campana (mm)
