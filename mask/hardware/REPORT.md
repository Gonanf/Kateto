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
