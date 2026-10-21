# Firmware ESP32 — Controlador de Servos MASK-7

Controlador de bajo nivel para la mascara fisica Hannya. Maneja tres servos PWM (mandibula y ojos) y un pulso digital para solenoide de campana sobre ESP32 WROOM-32.

## Compilacion y Ejecucion de Tests Nativos

La logica de interpolacion y parseo esta desacoplada del core de Arduino en `servo_core.cpp` (C++17 puro) para permitir validacion en host:

```bash
g++ -std=c++17 -Wall -Wextra -o /tmp/msc_test mask/hardware/firmware/test/test_servo_core.cpp mask/hardware/firmware/mask_servo_esp32/servo_core.cpp && /tmp/msc_test
```

Salida esperada:
```
ALL TESTS PASSED (12)
```

## Compilacion y Flasheo en ESP32

Requisitos: `arduino-cli` con el core `esp32:esp32`.

### Compilacion:
```bash
arduino-cli compile --fqbn esp32:esp32:esp32 mask/hardware/firmware/mask_servo_esp32
```

### Flasheo por USB:
```bash
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32 mask/hardware/firmware/mask_servo_esp32
```

- **Placa (FQBN):** `esp32:esp32:esp32` (NodeMCU-32S / ESP32 Dev Module standard)
- **Particion:** `default` (4MB con spiffs o standard app partition table)
- **Velocidad Serial:** 115200 baud, 8N1

## Tabla de Pines y Actuadores

| Pin ESP32 | Funcion / Actuador | Metodo de Control | Canal LEDC | Rango / Pulso |
|-----------|--------------------|-------------------|------------|---------------|
| GPIO 13   | Mandibula (Jaw)    | PWM LEDC (50 Hz)  | Canal 0    | 10° .. 85° (500 .. 2500 µs) |
| GPIO 14   | Ojos Pan (Eye X)   | PWM LEDC (50 Hz)  | Canal 1    | 25° .. 155° (500 .. 2500 µs) |
| GPIO 25   | Ojos Tilt (Eye Y)  | PWM LEDC (50 Hz)  | Canal 2    | 35° .. 145° (500 .. 2500 µs) |
| GPIO 26   | Campana (Bell)     | Digital (MOSFET)  | N/A        | HIGH durante pulso (~120 ms) |
| GPIO 2    | Status LED onboard | Digital           | N/A        | Indicador de actividad / pulso |
