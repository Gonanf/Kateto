#include "../mask_servo_esp32/servo_core.h"
#include <cstdio>
#include <cstdlib>

static const char* current_test_name = "";

#define TEST_ASSERT(cond) \
  do { \
    if (!(cond)) { \
      std::fprintf(stderr, "FAIL in %s: %s (line %d)\n", current_test_name, #cond, __LINE__); \
      std::exit(1); \
    } \
  } while (0)

static void t01_parse_full() {
  current_test_name = "t01_parse_full";
  maskservo::Limits limits;
  maskservo::Pose cur{20, 30, 40, false};
  auto res = maskservo::parse_command("{\"jaw\":40,\"eye_x\":100,\"eye_y\":80,\"bell\":true}", cur, limits);
  TEST_ASSERT(res.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(res.pose.jaw == 40);
  TEST_ASSERT(res.pose.eye_x == 100);
  TEST_ASSERT(res.pose.eye_y == 80);
  TEST_ASSERT(res.pose.bell == true);
  TEST_ASSERT(res.error.empty());
}

static void t02_partial_keeps_current() {
  current_test_name = "t02_partial_keeps_current";
  maskservo::Limits limits;
  maskservo::Pose cur{45, 90, 85, true};
  auto res = maskservo::parse_command("{\"eye_x\":120}", cur, limits);
  TEST_ASSERT(res.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(res.pose.jaw == 45);
  TEST_ASSERT(res.pose.eye_x == 120);
  TEST_ASSERT(res.pose.eye_y == 85);
  TEST_ASSERT(res.pose.bell == true);
  TEST_ASSERT(res.error.empty());
}

static void t03_clamp_high() {
  current_test_name = "t03_clamp_high";
  maskservo::Limits limits;
  maskservo::Pose cur;
  auto res = maskservo::parse_command("{\"jaw\":200}", cur, limits);
  TEST_ASSERT(res.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(res.pose.jaw == 85);
}

static void t04_clamp_low() {
  current_test_name = "t04_clamp_low";
  maskservo::Limits limits;
  maskservo::Pose cur;
  auto res = maskservo::parse_command("{\"jaw\":-30,\"eye_y\":0}", cur, limits);
  TEST_ASSERT(res.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(res.pose.jaw == 10);
  TEST_ASSERT(res.pose.eye_y == 35);
}

static void t05_malformed_leaves_pose() {
  current_test_name = "t05_malformed_leaves_pose";
  maskservo::Limits limits;
  maskservo::Pose cur{33, 77, 88, false};
  auto res = maskservo::parse_command("{\"jaw\":}", cur, limits);
  TEST_ASSERT(res.status == maskservo::ParseStatus::Malformed);
  TEST_ASSERT(res.pose.jaw == 33);
  TEST_ASSERT(res.pose.eye_x == 77);
  TEST_ASSERT(res.pose.eye_y == 88);
  TEST_ASSERT(res.pose.bell == false);
  TEST_ASSERT(!res.error.empty());
}

static void t06_empty_line() {
  current_test_name = "t06_empty_line";
  maskservo::Limits limits;
  maskservo::Pose cur{33, 77, 88, false};
  auto res1 = maskservo::parse_command("", cur, limits);
  TEST_ASSERT(res1.status == maskservo::ParseStatus::Empty);
  TEST_ASSERT(res1.pose.jaw == 33);
  TEST_ASSERT(res1.error.empty());

  auto res2 = maskservo::parse_command("   ", cur, limits);
  TEST_ASSERT(res2.status == maskservo::ParseStatus::Empty);
  TEST_ASSERT(res2.pose.jaw == 33);
  TEST_ASSERT(res2.error.empty());
}

static void t07_bell_variants() {
  current_test_name = "t07_bell_variants";
  maskservo::Limits limits;
  maskservo::Pose cur;

  auto r1 = maskservo::parse_command("{\"bell\":true}", cur, limits);
  TEST_ASSERT(r1.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(r1.pose.bell == true);

  auto r2 = maskservo::parse_command("{\"bell\":1}", cur, limits);
  TEST_ASSERT(r2.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(r2.pose.bell == true);

  auto r3 = maskservo::parse_command("{\"bell\":false}", cur, limits);
  TEST_ASSERT(r3.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(r3.pose.bell == false);

  auto r4 = maskservo::parse_command("{\"bell\":0}", cur, limits);
  TEST_ASSERT(r4.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(r4.pose.bell == false);
}

static void t08_unknown_keys_ignored() {
  current_test_name = "t08_unknown_keys_ignored";
  maskservo::Limits limits;
  maskservo::Pose cur;
  auto res = maskservo::parse_command("{\"jaw\":30,\"zzz\":9}", cur, limits);
  TEST_ASSERT(res.status == maskservo::ParseStatus::Ok);
  TEST_ASSERT(res.pose.jaw == 30);
}

static void t09_slew_rate() {
  current_test_name = "t09_slew_rate";
  maskservo::Limits limits;
  maskservo::Engine engine(limits);
  maskservo::Pose p;
  p.jaw = 10;
  engine.set_pose(p);
  while (!engine.settled()) {
    engine.tick(20);
  }
  TEST_ASSERT(engine.jaw() == 10);

  p.jaw = 85;
  engine.set_pose(p);
  engine.tick(16);
  TEST_ASSERT(engine.jaw() == 19);
}

static void t10_converges_exact() {
  current_test_name = "t10_converges_exact";
  maskservo::Limits limits;
  maskservo::Engine engine(limits);
  maskservo::Pose p;
  p.jaw = 10;
  engine.set_pose(p);
  while (!engine.settled()) {
    engine.tick(20);
  }
  p.jaw = 85;
  engine.set_pose(p);
  for (int i = 0; i < 200; ++i) {
    engine.tick(16);
  }
  TEST_ASSERT(engine.settled());
  TEST_ASSERT(engine.jaw() == 85);
}

static void t11_bell_pulse_expires() {
  current_test_name = "t11_bell_pulse_expires";
  maskservo::Engine engine;
  engine.pulse_bell(120);
  TEST_ASSERT(engine.bell() == true);
  engine.tick(60);
  TEST_ASSERT(engine.bell() == true);
  engine.tick(60);
  TEST_ASSERT(engine.bell() == false);
}

static void t12_no_overshoot() {
  current_test_name = "t12_no_overshoot";
  maskservo::Limits limits;
  maskservo::Engine engine(limits);
  maskservo::Pose p;
  p.jaw = 10;
  engine.set_pose(p);
  while (!engine.settled()) {
    engine.tick(20);
  }
  p.jaw = 85;
  engine.set_pose(p);
  while (!engine.settled()) {
    engine.tick(7);
    TEST_ASSERT(engine.jaw() <= 85);
  }
  TEST_ASSERT(engine.jaw() == 85);
}

int main() {
  t01_parse_full();
  t02_partial_keeps_current();
  t03_clamp_high();
  t04_clamp_low();
  t05_malformed_leaves_pose();
  t06_empty_line();
  t07_bell_variants();
  t08_unknown_keys_ignored();
  t09_slew_rate();
  t10_converges_exact();
  t11_bell_pulse_expires();
  t12_no_overshoot();

  std::printf("ALL TESTS PASSED (12)\n");
  return 0;
}
