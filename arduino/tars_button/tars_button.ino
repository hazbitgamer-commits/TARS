/*
  TARS's finger — a servo that presses the PC's power button.

  The problem it solves: everything else TARS can do to bring the PC back
  needs something on the network to be awake. This needs nothing. It presses
  the button like a person would, so it works from a shutdown, from a crash,
  and from a power cut — states no software on the PC can recover from,
  because the PC isn't running.

  How it decides: TARS sends a tick every 20 seconds while it's alive. This
  sketch doesn't understand anything else — it just counts. If the ticks
  stop for three minutes, the PC isn't running, so it presses the button
  once. A dead man's switch, in hardware, where nothing can kill it.

  WIRING
    Servo signal (orange/yellow) -> pin 9
    Servo power  (red)           -> 5V
    Servo ground (brown/black)   -> GND
    Arduino power                -> 9V barrel jack if you have one, so it
                                    stays alive when the PC doesn't. USB to
                                    the PC then carries only data.
                                    (If your motherboard keeps USB powered
                                    while off, PC USB alone works too.)

  SAFETY, because this thing can turn a computer off
    - it only ever taps. Holding the button four seconds is a hard
      power-off; PRESS_MS is 400.
    - after any press it ignores everything for ten minutes, so a PC that
      is slow to boot never gets pressed twice.
    - TARS says "disarm" before a deliberate shutdown, so turning the PC
      off on purpose doesn't start a fight with it.
    - unplug the servo and the whole thing is inert.

  COMMANDS (one per line, from TARS)
    T          tick — I'm alive
    P          press now
    D<mins>    disarm for that many minutes (deliberate shutdown)
    A          arm again
    ?          report status
*/

#include <Servo.h>

const int SERVO_PIN   = 9;
// REST is the HIGHER number, so the arm swings DOWN onto the button. Flip
// these two round to reverse the direction; widen the gap for more travel.
const int REST_ANGLE  = 110;   // finger clear of the button
const int PRESS_ANGLE = 20;    // finger pressing — 90 degrees of travel
// A tap, NOT long enough to force a shutdown (that needs four seconds).
// 400ms wasn't reliably depressing his button: under load an SG90 moves
// slowly, and the arm was heading back before it had finished pushing.
const int PRESS_MS    = 800;

const unsigned long SILENCE_MS  = 180000UL;   // 3 min with no tick = it's off
const unsigned long COOLDOWN_MS = 600000UL;   // 10 min before another press

Servo finger;
unsigned long lastTick   = 0;
unsigned long lastPress  = 0;
unsigned long disarmedTo = 0;
bool armed = true;
unsigned long presses = 0;

void setup() {
  Serial.begin(9600);
  finger.attach(SERVO_PIN);
  finger.write(REST_ANGLE);
  // NOTE: it stays attached for good. Detaching saved a little current and
  // stopped it humming, but a detached servo has no holding torque — the
  // arm went floppy, every press started from an unknown position, and a
  // limp arm can droop onto the very button it's meant to leave alone.
  // Holding REST firmly is worth the milliamps.
  lastTick = millis();      // assume alive at boot; the silence timer starts now
  Serial.println(F("TARS button ready"));
}

void pressAt(int angle) {
  if (angle < 0) angle = 0;
  if (angle > 180) angle = 180;
  finger.write(angle);
  delay(PRESS_MS);
  finger.write(REST_ANGLE);
  delay(400);               // let it get properly back before we stop caring
  lastPress = millis();
  lastTick = millis();      // give the PC a full silence window to boot
  presses++;
  Serial.print(F("PRESSED at ")); Serial.println(angle);
}

void press() { pressAt(PRESS_ANGLE); }

void report() {
  Serial.print(F("armed=")); Serial.print(armed ? 1 : 0);
  Serial.print(F(" silent=")); Serial.print((millis() - lastTick) / 1000);
  Serial.print(F("s presses=")); Serial.println(presses);
}

void handle(char c) {
  if (c == 'T') { lastTick = millis(); return; }
  if (c == 'P') { press(); return; }
  // X<angle> — press to a specific angle, for finding the right depth
  // against his actual button without reflashing between each try
  if (c == 'X') { pressAt((int)Serial.parseInt()); return; }
  if (c == 'A') { armed = true; disarmedTo = 0; Serial.println(F("ARMED")); return; }
  if (c == '?') { report(); return; }
  if (c == 'D') {
    long mins = Serial.parseInt();
    if (mins <= 0) mins = 60;
    if (mins > 720) mins = 720;             // never longer than half a day
    disarmedTo = millis() + (unsigned long)mins * 60000UL;
    armed = false;
    Serial.print(F("DISARMED ")); Serial.println(mins);
  }
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    // '?' is ASCII 63, BELOW 'A' — an A-to-Z filter silently swallowed the
    // status command, so it looked dead while working perfectly
    if ((c >= 'A' && c <= 'Z') || c == '?') handle(c);
  }

  // re-arm once a deliberate shutdown window has passed
  if (!armed && disarmedTo && (long)(millis() - disarmedTo) >= 0) {
    armed = true;
    disarmedTo = 0;
    lastTick = millis();     // don't press the instant we re-arm
  }

  if (!armed) return;
  if (millis() - lastPress < COOLDOWN_MS && lastPress != 0) return;
  if (millis() - lastTick > SILENCE_MS) press();
}
