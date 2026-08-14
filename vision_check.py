"""Checking the tracker behaves — without needing anyone in front of a camera.

The two complaints being tested here are his exact words: "if i smile, or
turn my head it loses me" and "the body tracking goes crazy". Both are
timing-and-identity problems, not model problems, so both can be tested with
made-up landmarks and a fake clock. No webcam, no lighting, no waiting for
him to sit down.

The fake landmarks matter: a real camera can't be told "now return these two
people in the opposite order", which is precisely the case that used to
throw the skeleton across the room.
"""
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vision_track as vt

passed = failed = 0


def check(name, got, want):
    global passed, failed
    ok = got == want
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"\n         got {got!r}, wanted {want!r}"))


def near(name, got, want, slack):
    global passed, failed
    ok = abs(got - want) <= slack
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {name}"
          + ("" if ok else f"\n         got {got}, wanted {want}±{slack}"))


def reset():
    vt._smoothed.clear()
    vt._sticky.clear()
    vt._names["people"] = []


def spread(a, b):
    """Average distance between two point lists."""
    return sum(((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
               for (x1, y1), (x2, y2) in zip(a, b)) / len(a)


print("\nsmoothing — does it actually calm the jitter?")
reset()
still = [(100 + i * 10, 200) for i in range(20)]           # a motionless body
jittery = [(x + (3 if i % 2 else -3), y + (3 if i % 3 else -3))
           for i, (x, y) in enumerate(still)]
vt._smooth("pose", still)
out = vt._smooth("pose", jittery)
check("a jittering point set is pulled back toward where it was",
      spread(out, still) < spread(jittery, still), True)

print("\nidentity — the bug that threw the skeleton across the room")
reset()
left = [(100 + i, 100) for i in range(20)]
right = [(900 + i, 100) for i in range(20)]
vt._smooth("pose", left)
vt._smooth("pose", right)
# MediaPipe makes no promise about ordering: same two bodies, opposite order
swapped_right = vt._smooth("pose", [(x + 1, y) for x, y in right])
swapped_left = vt._smooth("pose", [(x + 1, y) for x, y in left])
near("the body on the right stays on the right after a reorder",
     swapped_right[0][0], 901, 3)
near("the body on the left stays on the left after a reorder",
     swapped_left[0][0], 101, 3)
check("neither body was dragged toward the other",
      abs(swapped_right[0][0] - swapped_left[0][0]) > 700, True)

print("\nreappearing — someone stepping back into shot shouldn't lurch")
reset()
vt._smooth("pose", left)
for entry in vt._smoothed:
    entry["at"] = time.time() - vt.TRACK_FORGET - 1        # gone a while
back = vt._smooth("pose", right)
check("a body returning elsewhere starts fresh, not halfway there",
      back[0][0], right[0][0])

print("\nkinds don't cross-contaminate")
reset()
vt._smooth("hand", left)
face = vt._smooth("face", [(x + 2, y) for x, y in left])
check("a face is never smoothed against a hand in the same place",
      face[0][0], left[0][0] + 2)

print("\nnames — 'if i smile, or turn my head it loses me'")
reset()
vt._names["people"] = [{"name": "OWNER", "box": (100, 100, 200, 200)}]
check("named while DeepFace can see him", vt._name_for(150, 150, 100, 100), "OWNER")
vt._names["people"] = []                                   # he smiles; match fails
check("still named through a failed match", vt._name_for(150, 150, 100, 100), "OWNER")
check("the name follows him as he moves", vt._name_for(180, 170, 100, 100), "OWNER")
for seen in vt._sticky:
    seen["at"] = time.time() - vt.NAME_STICKS_FOR - 1
check("but it does expire eventually", vt._name_for(150, 150, 100, 100), "")

reset()
vt._names["people"] = [{"name": "OWNER", "box": (100, 100, 200, 200)}]
vt._name_for(150, 150, 100, 100)
vt._names["people"] = []
check("a different face across the room doesn't inherit his name",
      vt._name_for(900, 600, 100, 100), "")

print("\nvisibility — a guessed limb is worse than no limb")


class FakeLandmark:
    def __init__(self, x, y, visibility):
        self.x, self.y, self.visibility = x, y, visibility


class FakePose:
    """Stands in for the real model so the drawing code can be tested with
    landmarks of a chosen confidence."""

    def __init__(self, visibility):
        self.visibility = visibility
        self.seen_timestamps = []

    def detect_for_video(self, image, timestamp_ms):
        self.seen_timestamps.append(timestamp_ms)
        body = [FakeLandmark(0.3 + (i % 5) * 0.08, 0.3 + (i // 5) * 0.1,
                             self.visibility) for i in range(33)]
        return types.SimpleNamespace(pose_landmarks=[body])


try:
    import cv2
    import numpy as np

    def drawn_pixels(visibility):
        reset()
        real = vt._models["pose"], vt._models["face"], vt._models["hands"]
        vt._models["pose"] = FakePose(visibility)
        vt._models["face"] = vt._models["hands"] = None
        vt._models["loaded"] = True
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        vt.annotate(frame)
        vt._models["pose"], vt._models["face"], vt._models["hands"] = real
        return int((frame.sum(axis=2) > 0).sum())

    confident = drawn_pixels(0.95)
    unsure = drawn_pixels(0.1)
    check("a confident skeleton is drawn", confident > 500, True)
    check("an unsure one is not flung across the screen", unsure < confident / 3, True)

    print("\nVIDEO mode — the clock must only ever go up")
    reset()
    fake = FakePose(0.95)
    real = vt._models["pose"], vt._models["face"], vt._models["hands"]
    vt._models["pose"] = fake
    vt._models["face"] = vt._models["hands"] = None
    for _ in range(5):
        vt.annotate(np.zeros((480, 640, 3), dtype=np.uint8))
    vt._models["pose"], vt._models["face"], vt._models["hands"] = real
    stamps = fake.seen_timestamps
    check("every frame got a timestamp", len(stamps), 5)
    check("and each one was later than the last",
          all(b > a for a, b in zip(stamps, stamps[1:])), True)
    print("\ntwo feeds at once — the dashboard and the livestream")
    reset()
    import threading

    class CountingPose(FakePose):
        """Records every timestamp it is handed, from any thread."""

        def __init__(self):
            super().__init__(0.95)
            self.lock = threading.Lock()
            self.out_of_order = 0
            self.last = -1

        def detect_for_video(self, image, timestamp_ms):
            with self.lock:
                if timestamp_ms <= self.last:
                    self.out_of_order += 1
                self.last = timestamp_ms
            time.sleep(0.001)          # long enough for a race to show itself
            return super().detect_for_video(image, timestamp_ms)

    counter = CountingPose()
    real = vt._models["pose"], vt._models["face"], vt._models["hands"]
    vt._models["pose"] = counter
    vt._models["face"] = vt._models["hands"] = None

    def hammer():
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        for _ in range(20):
            vt.annotate(blank.copy())

    threads = [threading.Thread(target=hammer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    vt._models["pose"], vt._models["face"], vt._models["hands"] = real
    check("no timestamp arrived out of order with both feeds running",
          counter.out_of_order, 0)
    check("every frame from both feeds was tracked",
          len(counter.seen_timestamps), 40)
except ImportError:
    print("  (skipped — no cv2/numpy)")

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
