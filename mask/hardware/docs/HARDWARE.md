# Hardware y Arquitectura Electrica — MASK-7

Guia de diseno electronico, alimentacion, seguridad electrica y lista de materiales (BOM) para la mascara fisica Hannya.

---

## 1. Asignacion de Pines (Pinout ESP32 WROOM-32)

| GPIO ESP32 | Etiqueta en Placa | Tipo I/O | Destino / Modulo | Notas |
|------------|-------------------|----------|------------------|-------|
| GPIO 13    | D13               | PWM Out  | Signal Servo Mandibula (Jaw) | Canal LEDC 0 (50 Hz) |
| GPIO 14    | D14               | PWM Out  | Signal Servo Ojos Pan (Eye X)| Canal LEDC 1 (50 Hz) |
| GPIO 25    | D25               | PWM Out  | Signal Servo Ojos Tilt (Eye Y)| Canal LEDC 2 (50 Hz) |
| GPIO 26    | D26               | Dig Out  | Gate MOSFET Campana (Bell)   | Pulso digital via R=100Ω |
| GPIO 2     | D2                | Dig Out  | LED Onboard de Estado        | Indicador visual |
| GND        | GND               | Power    | Barra GND Comun              | Referencia comun obligatoria |
| 5V (VIN)   | VIN / 5V          | Power In | Alimentacion de la logica    | Desde puerto USB o BEC 5V |

---

## 2. Esquema de Alimentacion y Seguridad

### Regla Critica: Separacion de Rails
**Jamas alimentar los servos ni el solenoide desde el pin 5V (VBUS) del ESP32 ni directamente desde el puerto USB-C de un telefono u ordenador portatil.**

- **Rail Logico (ESP32):** 5 V regulados internamente a 3.3 V. Consume ~80 - 150 mA. Puede alimentarse via cable USB.
- **Rail de Potencia (Servos):** Fuente dedicada de **5 V DC / 2 A continuo (3 A pico)**. Puede provenir de un BEC conmutado (Step-Down DC-DC), un cargador USB dedicado de 2A+ o una bateria PowerBank independiente.
- **Tierra Comun (GND):** El GND de la fuente de potencia de los servos y el GND del ESP32 **deben estar interconectados** para garantizar la misma referencia en las lineas de senal PWM.

### Filtrado y Desacoplo
- **Capacitor electrolitico de 470 µF / 16 V** (baja ESR) en paralelo con el rail de potencia de 5V lo mas cerca posible de los conectores de servos. Esto absorbe las caidas de tension transitorias provocadas por el arranque simultaneo de los motores.
- **Capacitores ceramicos de 100 nF (0.1 µF)** en paralelo con la alimentacion individual de cada servo para amortiguar ruido de conmutacion de alta frecuencia.

---

## 3. Circuito del Solenoide de la Campana

El solenoide es una carga inductiva que demanda una corriente instantanea considerable y genera sobretensiones inversas (flyback) destructivas al desconectarse.

### Diagrama Esquemático:
```
  + Rail Solenoide (5V o 12V)
        │
        ├───[+ Solenoide -]───┐
        │        │             │
        └───[|< 1N4007 ]──────┤
           (catodo a +V)      │
                              ├── Drain (D)
                              │
  GPIO 26 ──[ 100 Ω ]───┬────┤ IRLZ44N (Logic-Level N-MOSFET)
                        │     │
                     [10 kΩ]  └── Source (S)
                        │             │
                       GND           GND
```

### Componentes del Driver:
1. **MOSFET:** `IRLZ44N` (nivel logico, conmuta completamente saturado con Vgs = 3.3 V desde el GPIO del ESP32).
2. **Resistencia de Gate en Serie (100 Ω):** Limita la corriente de carga de la capacitancia parasita del gate del MOSFET, protegiendo el pin GPIO del microcontrolador.
3. **Resistencia Pulldown (10 kΩ):** Conectada entre Gate y GND para asegurar que el MOSFET permanezca apagado durante el arranque, reset o estado de alta impedancia (Hi-Z) del microcontrolador.
4. **Diodo Flyback (1N4007):** Conectado en antiparalelo directo a los bornes de la bobina del solenoide (catodo a V+, anodo a Drain). Absorbe el pulso de contratension inductiva al desconectar el transistor, evitando quemar el MOSFET.

---

## 4. Limites Mecanicos y Consumo de Potencia

### Por que Mandibula 10° .. 85° (y no 0° .. 180°):
Los mecanismos articulados de una mascara presentan topes fisicos duros:
- Si un servo se envia a 0° o 180° y choca contra la articulacion de la mascara o la tension del resorte, entrara en condicion de **stall (motor trabado)**.
- En condicion de stall, un micro-servo MG90S consume hasta **700 - 800 mA**, calentando sus bobinas y el circuito integrado interno en segundos hasta destruirse o provocar un reset por baja tension (brownout) en el ESP32.
- Los limites `jaw_min = 10°` (maxima apertura sin forzar bisagras) y `jaw_max = 85°` (cierre completo sin compresion excesiva) garantizan vida util y proteccion del engranaje metalico.

### Presupuesto de Consumo:
- ESP32 WROOM-32 activo: ~120 mA
- 3x MG90S reposo/movimiento suave: 3 × 100 mA = 300 mA
- 3x MG90S pico de aceleracion simultanea: 3 × 500 mA = 1.5 A
- 1x Solenoide de campana (5V mini): ~500 mA durante 120 ms
- **Consumo pico combinado:** ~2.1 A.

---

## 5. Lista de Materiales (Bill of Materials - BOM)

| Item | Descripcion | Cantidad | Notas | Precio Est. (USD) |
|------|-------------|----------|-------|-------------------|
| 1 | ESP32 NodeMCU-32S (WROOM-32) | 1 | Microcontrolador 38 pines / USB micro o C | $4.50 |
| 2 | Micro-servo TowerPro MG90S | 3 | Engranaje metalico, 180°, con brazos y tornillos | $9.00 ($3 c/u) |
| 3 | Mini Solenoide 5V DC (JF-0530B o similar) | 1 | Carrera 5 mm, retorno por resorte para campana | $3.50 |
| 4 | Campana / Cuenco resonador metalico | 1 | Campana pequena tipo rin / tibetana (diám. 40mm) | $3.00 |
| 5 | MOSFET N-Channel IRLZ44N (TO-220) | 1 | Logic Level (Vgs(th) < 2.5V) | $0.80 |
| 6 | Diodo rectificador 1N4007 | 1 | Diodo de recuperacion / flyback para solenoide | $0.10 |
| 7 | Resistencia 100 Ω (1/4 W) | 1 | Resistencia serie de Gate | $0.05 |
| 8 | Resistencia 10 kΩ (1/4 W) | 1 | Resistencia pulldown de Gate | $0.05 |
| 9 | Capacitor electrolitico 470 µF / 16V | 1 | Buffer rail 5V servos | $0.20 |
| 10 | Capacitores ceramicos 100 nF | 3 | Desacoplo por servo | $0.15 |
| 11 | Modulo Regulador Step-Down UBEC 5V 3A | 1 | Alimentacion principal de potencia (opcional si hay powerbank)| $2.50 |
| 12 | Cableado, tiras de pines, conector JST/Dupont | 1 set | Conexionado interno | $2.00 |
| 13 | Tornilleria M2 y M3 (acero inox) | 1 pack | Fijacion de soportes y servos | $2.50 |
| **TOTAL** | | | | **~$28.35 USD** |
