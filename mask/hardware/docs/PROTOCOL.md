# Protocolo de Comunicacion Serie / BLE — MASK-7

Documentacion del protocolo de control para los actuadores fisicos de la mascara Hannya (ESP32).

---

## 1. Parametros de Capa Fisica y Framing

- **Transporte principal:** USB Serial (CDC / UART via puente USB-UART CP2102/CH340).
- **Configuracion Serial:** 115200 baudios, 8 bits de datos, sin paridad, 1 bit de parada (8N1).
- **Framing:** Cada comando es una linea JSON delimitada por salto de linea (`\n` o `\r\n`).
- **Codificacion:** UTF-8.
- **Tamano maximo de paquete:** 96 bytes por linea (los caracteres adicionales antes del salto de linea se descartan para prevenir desbordamiento de buffer).

---

## 2. Formato de Comandos (Host -> ESP32)

Los comandos son objetos JSON planos (sin anidamiento) con una o mas de las siguientes claves:

| Clave   | Tipo           | Rango Valido | Por Defecto / Neutral | Descripcion |
|---------|----------------|--------------|-----------------------|-------------|
| `jaw`   | Entero (grados)| 10 .. 85     | 85 (cerrada/reposo)   | Servo mandibula (movimiento cascanueces) |
| `eye_x` | Entero (grados)| 25 .. 155    | 90 (centro)           | Servo eje horizontal de ambos ojos (pan) |
| `eye_y` | Entero (grados)| 35 .. 145    | 90 (centro)           | Servo eje vertical de ambos ojos (tilt) |
| `bell`  | Booleano / Int | true/false/1/0 | false               | Pulso de solenoide de campana (~120 ms, edge-triggered) |

*Nota de tipos:* Los ejes son **enteros**; un valor flotante o entre comillas (`"jaw":45.5`, `"jaw":"40"`) invalida el comando entero (`Malformed`) y no aplica ningun campo.

### Semantica de Claves Ausentes
El protocolo es de estado incremental: cualquier clave omitida en el JSON conserva su valor objetivo previo (`current`). No es necesario reenviar todos los ejes si solo uno se modifica.

### Clamping Automatico
Cualquier valor numerico que exceda los limites definidos en el firmware es clampeado automaticamente al limite mas cercano sin generar error (ej. `jaw: 200` se ejecuta como `jaw: 85`).

### Claves Desconocidas
Cualquier clave adicional desconocida es ignorada por el firmware para permitir retrocompatibilidad y depuracion sin romper la transmision.

---

## 3. Respuestas del Firmware (ESP32 -> Host)

### Mensaje de Inicio (Boot)
Al resetear o encender el ESP32:
```json
{"boot":"mask-servo","v":1}
```

### Confirmacion de Comando Valido (ACK)
```json
{"ok":1}
```

### Reporte de Error (Malformed)
Cuando una linea no cumple la sintaxis esperada (ej. llaves faltantes, claves sin valor, valor no numerico):
```json
{"err":"<motivo>"}
```
*Ejemplos:* `{"err":"missing_value"}`, `{"err":"bad_value:jaw"}`.
Cuando se produce un error, la pose actual y los objetivos en curso se mantienen inalterados.

---

## 4. Temporizacion, Tasas y Presupuesto de Latencia

- **Frecuencia maxima de envio:** 60 Hz (~16.6 ms entre comandos). Frecuencias mayores pueden saturar el buffer UART o ser redundantes dado el slew rate de los servos.
- **Slew Rate interno (interpolacion en firmware):**
  - Mandibula: 600 °/s
  - Ojos (X e Y): 400 °/s
  - Calculo por tick: `floor(rate * dt / 1000)` con avance minimo garantizado de 1 grado y prevencion estricta de overshoot.
- **Pulso de campana:** Es **edge-triggered** — el pulso de 120 ms se dispara en el flanco `false -> true`; repetir `true` en cada frame **no** re-arma el pulso (un solenoide energizado continuo se quema); para otro click hay que mandar `false` y despues `true`. Enviar `bell: false` no trunca un pulso ya iniciado.
- **Presupuesto de latencia:**
  - Serial TX/RX (96 bytes @ 115200 bps): < 1.0 ms
  - Parseo y planificacion en ESP32: < 0.2 ms
  - Periodo PWM (50 Hz): 20 ms
  - Respuesta mecanica del servo (MG90S): 20 - 30 ms
  - **Latencia total extremo a extremo:** < 50 ms.

---

## 5. Watchdog de Seguridad

Si transcurren mas de **2000 ms (2 segundos)** sin recibir un comando valido por el puerto serial, el firmware ejecuta automaticamente `neutral()`:
- Mandibula: a reposo (`jaw_max = 85°`)
- Ojos: al centro (`eye_x = 90°`, `eye_y = 90°`)
- Campana: apagada (`bell = false`)

Esto previene que la mascara quede trabada en una posicion tensa si el proceso en el host crashea o el cable se desconecta.

---

## 6. Ejemplos de Transmision

```
Host -> ESP32:  {"jaw":40,"eye_x":100,"eye_y":80}
ESP32 -> Host:  {"ok":1}

Host -> ESP32:  {"bell":1}
ESP32 -> Host:  {"ok":1}

Host -> ESP32:  {"jaw":200}
ESP32 -> Host:  {"ok":1}   (firmware clampea a 85 internamente)

Host -> ESP32:  {"jaw":}
ESP32 -> Host:  {"err":"missing_value"}
```

---

## 7. Mapeo desde el Sistema Kateto

Kateto procesa audio y genera eventos sincronizados. El mapeo sugerido hacia MASK-7 es:

1. **Mandibula (`jaw`):**
   - Fuente: `audio_output/viseme`
   - Metrica: Apertura de boca / `jawOffsetX` normalizado [0.0, 1.0].
   - Mapeo lineal: `jaw = 85 - int(jaw_norm * (85 - 10))`
     (0.0 = cerrada / 85°, 1.0 = maxima apertura / 10°).
2. **Ojos (`eye_x`, `eye_y`):**
   - Fuente: Puntos de atencion o `headOffsetY` / mirada del interlocutor.
   - `eye_x = 90 + int(pan_norm * 35)`  (rango seguro 55° a 125°)
   - `eye_y = 90 + int(tilt_norm * 30)` (rango seguro 60° a 120°)
3. **Campana (`bell`):**
   - Fuente: Deteccion de evento de enfasis / gong / campana de alerta o palabra clave ceremonial.
   - Genera: `{"bell": true}`.

---

## 8. Camino Alterno Diferido: Bluetooth LE (NUS)

Para operacion inalambrica sin cable USB:
- **Servicio:** Nordic UART Service (NUS).
- **UUID de Servicio:** `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
- **RX Characteristic (Write without response):** `6E400002-B5A3-F393-E0A9-E50E24DCCA9E`
- **TX Characteristic (Notify):** `6E400003-B5A3-F393-E0A9-E50E24DCCA9E`
- **Framing:** Exactamente las mismas lineas JSON terminadas en `\n` delimitadas a paquetes MTU de hasta 128 bytes.
- **Implementacion:** Postergada para etapa posterior; el protocolo serial descripto es 100% reutilizable sobre BLE sin cambiar la sintaxis ni el motor `servo_core`.
