# Reporte de Implementacion — MASK-7

Controlador de servos para la mascara fisica Hannya (ESP32).

---

## 1. Archivos Creados

Se escribieron los siguientes 15 archivos bajo `mask/hardware/`:

1. `mask/hardware/firmware/mask_servo_esp32/servo_core.h`: Declaraciones C++17 puras de `Limits`, `Pose`, `ParseResult`, `parse_command` y `Engine`.
2. `mask/hardware/firmware/mask_servo_esp32/servo_core.cpp`: Implementacion desacoplada de hardware; parser JSON plano, slew rate (600°/s jaw, 400°/s ojos) sin overshoot, temporizador de campana (120 ms).
3. `mask/hardware/firmware/test/test_servo_core.cpp`: Suite de 12 tests unitarios nativos con asserts independientes.
4. `mask/hardware/firmware/mask_servo_esp32/mask_servo_esp32.ino`: Cascaron de I/O para ESP32 (LEDC a 50 Hz en GPIO 13, 14, 25; campana en GPIO 26; LED status en GPIO 2; buffer serial de 96 bytes; watchdog de seguridad 2000 ms).
5. `mask/hardware/firmware/README.md`: Instrucciones de compilacion nativa, flasheo con `arduino-cli`, configuracion de board y tabla pin-actuador.
6. `mask/hardware/tools/mask_servo_cli.py`: CLI de host (Python 3 stdlib) con modos `--sim`, `--port`, `--cmd`, `--script` y validacion estricta con clamping.
7. `mask/hardware/tools/test_cli.py`: Suite de 6 tests pytest para el CLI.
8. `mask/hardware/docs/PROTOCOL.md`: Especificacion de protocolo serie 115200 8N1, JSON line-delimited, watchdog, latencia, mapeo desde visemas de Kateto y diseno BLE diferido (NUS).
9. `mask/hardware/docs/HARDWARE.md`: Guia de conexion electrica, rail dedicado de 5V 2A para servos, desacoplo (470 µF + 100 nF), circuito de solenoide con IRLZ44N y flyback 1N4007, y BOM con precios.
10. `mask/hardware/cad/params.scad`: Dimensiones y tolerancias parametricas para micro-servos MG90S, solenoide JF-0530B y tornilleria M2/M3.
11. `mask/hardware/cad/jaw_mount.scad`: Soporte imprimible FDM para servo de mandibula.
12. `mask/hardware/cad/eye_mount.scad`: Soporte dual para servos de ojos pan/tilt.
13. `mask/hardware/cad/bell_mount.scad`: Soporte para solenoide percutor y cuenco de campana.
14. `mask/hardware/cad/README.md`: 5 medidas a verificar en la mascara real, settings de impresion PETG e instrucciones de exportacion a STL.
15. `mask/hardware/REPORT.md`: Este reporte.

---

## 2. Comandos Ejecutados y Resultados

### Autochequeo 1: Tests unitarios de firmware nativo C++17
```bash
g++ -std=c++17 -Wall -Wextra -o /tmp/msc_test mask/hardware/firmware/test/test_servo_core.cpp mask/hardware/firmware/mask_servo_esp32/servo_core.cpp && /tmp/msc_test
```
**Resultado:**
- Codigo de salida: `0`
- Salida estandar:
  ```
  ALL TESTS PASSED (12)
  ```
- Compilacion limpia sin warnings (`-Wall -Wextra`).

### Autochequeo 2: Tests del CLI de host
```bash
python3 -m pytest mask/hardware/tools/test_cli.py -q
```
**Resultado:**
- Codigo de salida: `0`
- Salida estandar:
  ```
  ......                                                                   [100%]
  6 passed in 0.39s
  ```

---

## 3. Lo que NO se pudo verificar

- **Hardware fisico real:** No se conecto ningun microcontrolador ESP32 real, servos MG90S ni solenoide.
- **Compilacion de `mask_servo_esp32.ino` con toolchain ESP32:** No se encuentra instalado `arduino-cli` ni el core `esp32:esp32` en el contenedor.
- **Renderizado 3D de modelos CAD:** No se encuentra instalado el binario `openscad` en el contenedor para generar los archivos `.stl`.

---

## 4. Decisiones de Diseno Tomadas

1. **Desacoplamiento logica / hardware:** Toda la logica de parseo, clamping, interpolacion slew-rate y duracion del pulso reside exclusivamente en `servo_core.cpp` (C++17 estandar, sin dependencias de Arduino), permitiendo ejecucion nativa de tests en CI/host.
2. **Control PWM sin librerias externas:** El sketch `.ino` emplea directamente el periferico LEDC nativo del ESP32 a 50 Hz y 16 bits de resolucion con la macro `angle_to_duty(angle)` para pulsos estandar de 500 a 2500 µs, eliminando la necesidad de `ESP32Servo`.
3. **Watchdog de seguridad activo:** Ante desconexion del cable o caida del host superior a 2000 ms, el firmware fuerza la pose a `neutral()` (mandibula cerrada a 85°, ojos al centro a 90°, campana inactiva) para evitar calentamiento de motores contra topes mecanicos.
4. **Validacion atomica en el CLI:** El script parser de `mask_servo_cli.py` valida y clampea todas las lineas del script antes de ejecutar o escribir en `--sim` / `--port`, asegurando que comandos malformados salgan con codigo 3 sin emitir lineas parciales.

---

## 5. Delta 1

### Defecto Medido
Con clientes transmitiendo el estado a 30 Hz con `bell:true` continuo, el pulso de 120 ms se re-armaba en cada comando:
```
bell energizada acumulada con bell:true repetido = 330 ms de 330
```
Esto causaba energizacion continua del solenoide, con riesgo de calentamiento y degradacion del componente.

### Cambios Realizados
1. **`servo_core.h`**: Se agrego `bool bell_latch_ = false;` en la seccion privada de `class Engine`.
2. **`servo_core.cpp`**: Se implemento deteccion por flanco (`pose.bell && !bell_latch_`) en `Engine::set_pose` para disparar `pulse_bell(120)` unicamente en la transicion `false -> true` y registrar `bell_latch_ = pose.bell;`. En `Engine::neutral()` se agrego `bell_latch_ = false;`.
3. **`test_servo_core.cpp`**: Se anadio el test `t13_bell_edge_triggered()` para verificar activacion inicial, ignorado de re-armado ante 5 frames repetidos con `bell:true`, re-disparo ante nuevo flanco tras `bell:false`, y limpieza de latch tras `neutral()`. Actualizado mensaje a `ALL TESTS PASSED (13)`.
4. **`mask_servo_esp32.ino`**: En el bloque de timeout del watchdog (>= 2000 ms), se asignaron los valores objetivo de reposo (`current_pose.jaw = limits.jaw_max; current_pose.eye_x = 90; current_pose.eye_y = 90; current_pose.bell = false;`) en vez de la posicion interpolada instantanea, previniendo congelamientos por comandos parciales.
5. **`PROTOCOL.md`**: Se documento la campana como edge-triggered (evitando quemado de solenoide) y la especificacion de que los ejes deben ser estrictamente enteros (valores flotantes generan `Malformed`).

### Gates Ejecutados y Salida Real

**Gate 1: Tests unitarios de firmware (C++17)**
```bash
g++ -std=c++17 -Wall -Wextra -o /tmp/msc_test mask/hardware/firmware/test/test_servo_core.cpp mask/hardware/firmware/mask_servo_esp32/servo_core.cpp && /tmp/msc_test
```
Salida:
```
ALL TESTS PASSED (13)
```

**Gate 2: Tests del CLI de host (pytest)**
```bash
python3 -m pytest mask/hardware/tools/test_cli.py -q
```
Salida:
```
......                                                                   [100%]
6 passed in 0.28s
```
