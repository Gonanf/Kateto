#include "servo_core.h"
#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>

namespace maskservo {

static bool is_all_whitespace(const std::string& s) {
  for (char c : s) {
    if (!std::isspace(static_cast<unsigned char>(c))) {
      return false;
    }
  }
  return true;
}

static void skip_ws(const std::string& s, size_t& pos) {
  while (pos < s.size() && std::isspace(static_cast<unsigned char>(s[pos]))) {
    ++pos;
  }
}

ParseResult parse_command(const std::string& line, const Pose& current, const Limits& limits) {
  if (line.empty() || is_all_whitespace(line)) {
    return ParseResult{ParseStatus::Empty, current, ""};
  }

  size_t pos = 0;
  skip_ws(line, pos);

  if (pos >= line.size() || line[pos] != '{') {
    return ParseResult{ParseStatus::Malformed, current, "missing_opening_brace"};
  }
  ++pos;

  Pose out_pose = current;

  skip_ws(line, pos);
  if (pos < line.size() && line[pos] == '}') {
    ++pos;
    skip_ws(line, pos);
    if (pos != line.size()) {
      return ParseResult{ParseStatus::Malformed, current, "trailing_chars"};
    }
    return ParseResult{ParseStatus::Ok, out_pose, ""};
  }

  while (pos < line.size()) {
    skip_ws(line, pos);
    if (pos >= line.size()) {
      return ParseResult{ParseStatus::Malformed, current, "unclosed_brace"};
    }
    if (line[pos] != '"') {
      return ParseResult{ParseStatus::Malformed, current, "expected_key_quote"};
    }
    ++pos;

    std::string key;
    while (pos < line.size() && line[pos] != '"') {
      key += line[pos++];
    }
    if (pos >= line.size()) {
      return ParseResult{ParseStatus::Malformed, current, "unclosed_key"};
    }
    ++pos; // skip '"'

    skip_ws(line, pos);
    if (pos >= line.size() || line[pos] != ':') {
      return ParseResult{ParseStatus::Malformed, current, "expected_colon"};
    }
    ++pos; // skip ':'

    skip_ws(line, pos);
    if (pos >= line.size() || line[pos] == ',' || line[pos] == '}') {
      return ParseResult{ParseStatus::Malformed, current, "missing_value"};
    }

    std::string val_str;
    if (line[pos] == '"') {
      ++pos;
      while (pos < line.size() && line[pos] != '"') {
        val_str += line[pos++];
      }
      if (pos >= line.size()) {
        return ParseResult{ParseStatus::Malformed, current, "unclosed_string_value"};
      }
      ++pos;
    } else {
      while (pos < line.size() &&
             !std::isspace(static_cast<unsigned char>(line[pos])) &&
             line[pos] != ',' && line[pos] != '}') {
        val_str += line[pos++];
      }
    }

    if (key == "jaw" || key == "eye_x" || key == "eye_y") {
      if (val_str.empty()) {
        return ParseResult{ParseStatus::Malformed, current, "bad_value:" + key};
      }
      size_t v_idx = 0;
      bool negative = false;
      if (val_str[v_idx] == '-') {
        negative = true;
        ++v_idx;
      } else if (val_str[v_idx] == '+') {
        ++v_idx;
      }
      if (v_idx >= val_str.size()) {
        return ParseResult{ParseStatus::Malformed, current, "bad_value:" + key};
      }
      long long num = 0;
      for (; v_idx < val_str.size(); ++v_idx) {
        if (!std::isdigit(static_cast<unsigned char>(val_str[v_idx]))) {
          return ParseResult{ParseStatus::Malformed, current, "bad_value:" + key};
        }
        num = num * 10 + (val_str[v_idx] - '0');
        if (num > 10000) {
          num = 10000;
        }
      }
      if (negative) {
        num = -num;
      }

      int val = static_cast<int>(num);
      if (key == "jaw") {
        out_pose.jaw = std::max(limits.jaw_min, std::min(limits.jaw_max, val));
      } else if (key == "eye_x") {
        out_pose.eye_x = std::max(limits.eye_x_min, std::min(limits.eye_x_max, val));
      } else if (key == "eye_y") {
        out_pose.eye_y = std::max(limits.eye_y_min, std::min(limits.eye_y_max, val));
      }
    } else if (key == "bell") {
      if (val_str == "true" || val_str == "1") {
        out_pose.bell = true;
      } else if (val_str == "false" || val_str == "0") {
        out_pose.bell = false;
      } else {
        return ParseResult{ParseStatus::Malformed, current, "bad_value:bell"};
      }
    } else {
      // Ignored unknown key
    }

    skip_ws(line, pos);
    if (pos >= line.size()) {
      return ParseResult{ParseStatus::Malformed, current, "missing_closing_brace"};
    }
    if (line[pos] == ',') {
      ++pos;
      skip_ws(line, pos);
      if (pos < line.size() && line[pos] == '}') {
        return ParseResult{ParseStatus::Malformed, current, "trailing_comma"};
      }
    } else if (line[pos] == '}') {
      ++pos;
      skip_ws(line, pos);
      if (pos != line.size()) {
        return ParseResult{ParseStatus::Malformed, current, "trailing_chars"};
      }
      return ParseResult{ParseStatus::Ok, out_pose, ""};
    } else {
      return ParseResult{ParseStatus::Malformed, current, "expected_comma_or_brace"};
    }
  }

  return ParseResult{ParseStatus::Malformed, current, "unclosed_brace"};
}

static int advance_axis(int current, int target, int rate_deg_s, uint32_t dt_ms) {
  if (current == target || dt_ms == 0) {
    return current;
  }
  int diff = target - current;
  int dist = std::abs(diff);
  int step = static_cast<int>((static_cast<uint64_t>(rate_deg_s) * dt_ms) / 1000);
  if (step < 1) {
    step = 1;
  }
  if (dist <= step) {
    return target;
  }
  if (diff > 0) {
    return current + step;
  } else {
    return current - step;
  }
}

Engine::Engine() : Engine(Limits{}) {}

Engine::Engine(const Limits& limits)
    : limits_(limits),
      jaw_curr_(limits.jaw_max),
      jaw_target_(limits.jaw_max),
      eye_x_curr_(90),
      eye_x_target_(90),
      eye_y_curr_(90),
      eye_y_target_(90),
      bell_remaining_ms_(0) {}

void Engine::set_pose(const Pose& pose) {
  jaw_target_ = std::max(limits_.jaw_min, std::min(limits_.jaw_max, pose.jaw));
  eye_x_target_ = std::max(limits_.eye_x_min, std::min(limits_.eye_x_max, pose.eye_x));
  eye_y_target_ = std::max(limits_.eye_y_min, std::min(limits_.eye_y_max, pose.eye_y));
  if (pose.bell) {
    pulse_bell(120);
  }
}

void Engine::tick(uint32_t dt_ms) {
  jaw_curr_ = advance_axis(jaw_curr_, jaw_target_, 600, dt_ms);
  eye_x_curr_ = advance_axis(eye_x_curr_, eye_x_target_, 400, dt_ms);
  eye_y_curr_ = advance_axis(eye_y_curr_, eye_y_target_, 400, dt_ms);

  if (dt_ms >= bell_remaining_ms_) {
    bell_remaining_ms_ = 0;
  } else {
    bell_remaining_ms_ -= dt_ms;
  }
}

int Engine::jaw() const {
  return jaw_curr_;
}

int Engine::eye_x() const {
  return eye_x_curr_;
}

int Engine::eye_y() const {
  return eye_y_curr_;
}

bool Engine::bell() const {
  return bell_remaining_ms_ > 0;
}

void Engine::pulse_bell(uint32_t ms) {
  bell_remaining_ms_ = ms;
}

bool Engine::settled() const {
  return (jaw_curr_ == jaw_target_ &&
          eye_x_curr_ == eye_x_target_ &&
          eye_y_curr_ == eye_y_target_);
}

void Engine::neutral() {
  jaw_target_ = limits_.jaw_max;
  eye_x_target_ = 90;
  eye_y_target_ = 90;
  bell_remaining_ms_ = 0;
}

}  // namespace maskservo
