#include <Arduino.h>
#include "servo_core.h"

// Pines asignados segun diseno de hardware MASK-7
static const int PIN_JAW        = 13;
static const int PIN_EYE_X      = 14;
static const int PIN_EYE_Y      = 25;
static const int PIN_BELL       = 26;
static const int PIN_STATUS_LED = 2;

// Canales y parametros LEDC (50 Hz, 16 bits)
static const int CH_JAW   = 0;
static const int CH_EYE_X = 1;
static const int CH_EYE_Y = 2;
static const int PWM_FREQ = 50;
static const int PWM_RES  = 16;

// Conversion de angulo (0..180 deg) a valor de duty cycle para LEDC de ESP32.
// Frecuencia: 50 Hz (periodo 20,000 us).
// Resolucion: 16 bits (rango 0 .. 65535).
// Pulso servo estandar: 500 us (0 deg) a 2500 us (180 deg).
// Formula: duty = (500 + angle * 2000 / 180) * 65535 / 20000
#define angle_to_duty(angle) \
  ((uint32_t)((((uint32_t)(500 + ((angle) * 2000) / 180)) * 65535UL) / 20000UL))

static maskservo::Limits limits;
static maskservo::Pose current_pose;
static maskservo::Engine engine(limits);

static char rx_buf[96];
static size_t rx_idx = 0;
static uint32_t last_cmd_ms = 0;
static uint32_t last_tick_ms = 0;

void setup() {
  Serial.begin(115200);

  pinMode(PIN_BELL, OUTPUT);
  digitalWrite(PIN_BELL, LOW);

  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, LOW);

  ledcSetup(CH_JAW, PWM_FREQ, PWM_RES);
  ledcAttachPin(PIN_JAW, CH_JAW);

  ledcSetup(CH_EYE_X, PWM_FREQ, PWM_RES);
  ledcAttachPin(PIN_EYE_X, CH_EYE_X);

  ledcSetup(CH_EYE_Y, PWM_FREQ, PWM_RES);
  ledcAttachPin(PIN_EYE_Y, CH_EYE_Y);

  engine.neutral();
  current_pose.jaw = engine.jaw();
  current_pose.eye_x = engine.eye_x();
  current_pose.eye_y = engine.eye_y();
  current_pose.bell = false;

  ledcWrite(CH_JAW, angle_to_duty(engine.jaw()));
  ledcWrite(CH_EYE_X, angle_to_duty(engine.eye_x()));
  ledcWrite(CH_EYE_Y, angle_to_duty(engine.eye_y()));

  last_cmd_ms = millis();
  last_tick_ms = millis();

  Serial.println("{\"boot\":\"mask-servo\",\"v\":1}");
}

void loop() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (rx_idx > 0) {
        rx_buf[rx_idx] = '\0';
        std::string line(rx_buf);
        rx_idx = 0;

        maskservo::ParseResult res = maskservo::parse_command(line, current_pose, limits);
        if (res.status == maskservo::ParseStatus::Ok) {
          current_pose = res.pose;
          engine.set_pose(res.pose);
          last_cmd_ms = millis();
          Serial.println("{\"ok\":1}");
        } else if (res.status == maskservo::ParseStatus::Malformed) {
          Serial.print("{\"err\":\"");
          Serial.print(res.error.c_str());
          Serial.println("\"}");
        }
      }
    } else {
      if (rx_idx < sizeof(rx_buf) - 1) {
        rx_buf[rx_idx++] = c;
      }
    }
  }

  uint32_t now = millis();

  // Watchdog de seguridad: 2000 ms sin comando valido -> pose neutral
  if (now - last_cmd_ms >= 2000) {
    engine.neutral();
    current_pose.jaw = engine.jaw();
    current_pose.eye_x = engine.eye_x();
    current_pose.eye_y = engine.eye_y();
    current_pose.bell = false;
  }

  uint32_t dt = now - last_tick_ms;
  if (dt > 0) {
    engine.tick(dt);
    last_tick_ms = now;
  }

  ledcWrite(CH_JAW, angle_to_duty(engine.jaw()));
  ledcWrite(CH_EYE_X, angle_to_duty(engine.eye_x()));
  ledcWrite(CH_EYE_Y, angle_to_duty(engine.eye_y()));
  digitalWrite(PIN_BELL, engine.bell() ? HIGH : LOW);
  digitalWrite(PIN_STATUS_LED, engine.bell() ? HIGH : LOW);

  delay(2);
}
