#pragma once
#include <stdint.h>
#include <string>

namespace maskservo {

struct Limits {
  int jaw_min = 10, jaw_max = 85;
  int eye_x_min = 25, eye_x_max = 155;
  int eye_y_min = 35, eye_y_max = 145;
};

struct Pose {
  int jaw = 47;
  int eye_x = 90;
  int eye_y = 90;
  bool bell = false;
};

enum class ParseStatus { Ok, Empty, Malformed };

struct ParseResult {
  ParseStatus status = ParseStatus::Empty;
  Pose pose;           // input pose + campos parseados, ya clampeados
  std::string error;   // vacio salvo Malformed
};

// Parsea UNA linea JSON plana (sin \n). Claves ausentes conservan el valor de `current`.
// Valores numericos se clampean a `limits`. "bell" acepta true/false/1/0.
// Claves desconocidas se ignoran. Objeto plano, sin anidamiento ni escapes.
ParseResult parse_command(const std::string& line, const Pose& current, const Limits& limits);

class Engine {
 public:
  Engine();
  explicit Engine(const Limits& limits);
  void set_pose(const Pose& pose);   // fija targets; si pose.bell pasa a true, arranca pulso
  void tick(uint32_t dt_ms);         // avanza interpolacion
  int jaw() const;
  int eye_x() const;
  int eye_y() const;
  bool bell() const;                 // true mientras el pulso esta activo
  void pulse_bell(uint32_t ms);      // pulso de campana; tick() lo hace expirar
  bool settled() const;              // true si los 3 ejes estan exactamente en el target
  void neutral();                    // targets a (jaw_max, eye_x 90, eye_y 90), bell off

 private:
  Limits limits_;
  int jaw_curr_;
  int jaw_target_;
  int eye_x_curr_;
  int eye_x_target_;
  int eye_y_curr_;
  int eye_y_target_;
  uint32_t bell_remaining_ms_;
  bool bell_latch_ = false;
};

}  // namespace maskservo
