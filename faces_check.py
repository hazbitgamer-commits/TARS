"""Checking the face memory learns without poisoning itself.

Learning from your own answers is the dangerous kind of learning. Get one
match wrong, remember it as fact, and the wrong face is now part of who it
thinks you are — after which the next wrong match is easier, and the one
after that easier still. A system like that doesn't fail loudly, it drifts,
and by the time anyone notices it calls everyone by the same name.

So these tests are mostly about what it must REFUSE to learn. They use
made-up embeddings rather than photographs, because the question isn't
whether the model recognises anyone, it's whether the rules around it hold.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import faces as F

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


def unit(*values):
    """A normalised embedding — the shape everything downstream expects."""
    vec = np.array(values, dtype=np.float32)
    return vec / (np.linalg.norm(vec) + 1e-9)


def nudge(vec, amount):
    """The same face, seen a bit differently."""
    off = np.zeros_like(vec)
    off[1] = amount
    return (vec + off) / (np.linalg.norm(vec + off) + 1e-9)


BASE_FACE = unit(1, 0, 0, 0, 0)


def sideways(axis, amount):
    """A look that differs from BASE_FACE along its own axis, so several of
    them are distinct from each other and not just from the original."""
    values = [1.0, 0, 0, 0, 0]
    values[axis] = amount
    return unit(*values)


def fresh(*embeddings):
    return {"OWNER": {"embeddings": [e.tolist() for e in embeddings],
                      "learned": "2026-01-01"}}


print("\nnaming — and how sure it says it is")
db = fresh(BASE_FACE)
name, score, dist = F._match(BASE_FACE, db)
check("the identical face is named", name, "OWNER")
check("and reported as certain", score, 100)

name, score, dist = F._match(unit(0, 1, 0, 0, 0), db)
check("a completely different face is not named", name, None)
check("and gets no score at all", score, 0)

near = nudge(BASE_FACE, 0.35)
name, score, dist = F._match(near, db)
check("a similar face is still named", name, "OWNER")
check("but with a lower score than an exact match", score < 100, True)
check("the score is a real percentage", 0 < score <= 100, True)

print("\nwhat it refuses to learn")
db = fresh(BASE_FACE)
# far enough out to be a doubtful match but still inside naming range
shaky = nudge(BASE_FACE, 1.35)
_, _, shaky_dist = F._match(shaky, db)
check("a shaky match is inside the naming threshold",
      shaky_dist < F.MATCH_THRESHOLD, True)
check("...but is NOT learnt from", F._learn("OWNER", shaky, db, shaky_dist), False)
check("so the set is untouched", len(db["OWNER"]["embeddings"]), 1)

check("a face it can't name at all is never learnt",
      F._learn("OWNER", unit(0, 1, 0, 0, 0), db, 0.99), False)
check("and an unknown person can't be learnt into someone else's set",
      F._learn("NOBODY", BASE_FACE, db, 0.0), False)

print("\nwhat it does learn")
db = fresh(BASE_FACE)
check("the very same look again teaches nothing new",
      F._learn("OWNER", BASE_FACE, db, 0.0), False)
check("so nothing was stored", len(db["OWNER"]["embeddings"]), 1)

different = nudge(BASE_FACE, 0.55)
_, _, dist = F._match(different, db)
check("a confidently-matched NEW look is worth keeping",
      F._learn("OWNER", different, db, dist), True)
check("and it was stored", len(db["OWNER"]["embeddings"]), 2)
check("the count of sightings went up", db["OWNER"]["seen"], 1)

check("recognising that same new look again adds nothing further",
      F._learn("OWNER", different, db, dist), False)
check("still two looks", len(db["OWNER"]["embeddings"]), 2)

print("\nit learns the dark, which is the whole point")
db = fresh(BASE_FACE)
grew = 0
for axis in range(1, 5):        # four looks, each different from ALL the rest
    look = sideways(axis, 0.6)
    _, _, dist = F._match(look, db)
    if F._learn("OWNER", look, db, dist):
        grew += 1
check("several distinct looks accumulate", grew, 4)
check("a face is better known than when it started",
      len(db["OWNER"]["embeddings"]) > 1, True)

print("\nit never grows without limit")
db = fresh(BASE_FACE)
for i in range(F.MAX_GALLERY * 3):
    look = unit(1, 0.01 * (i + 1), 0.004 * (i + 1), 0, 0)
    db["OWNER"]["embeddings"].append(look.tolist())
    if len(db["OWNER"]["embeddings"]) > F.MAX_GALLERY:
        F._drop_dullest(db["OWNER"])
check("the set stops growing at the cap",
      len(db["OWNER"]["embeddings"]) <= F.MAX_GALLERY, True)
check("and the enrolment photo is never the one dropped",
      db["OWNER"]["embeddings"][0], BASE_FACE.tolist())

print("\ntwo people don't bleed into each other")
other = unit(0, 1, 0, 0, 0)
db = {"OWNER": {"embeddings": [BASE_FACE.tolist()]},
      "OTHER": {"embeddings": [other.tolist()]}}
check("each is named as themselves", F._match(BASE_FACE, db)[0], "OWNER")
check("and the other as themselves", F._match(other, db)[0], "OTHER")
check("neither can be learnt into the other's set",
      F._learn("OWNER", other, db, 1.0), False)
check("OWNER still has exactly one look", len(db["OWNER"]["embeddings"]), 1)

print("\nthe second look at a dark face replaces the first, if it's better")
people = [[{"box": (100, 100, 80, 80)}, (None, 0, 0.9)]]
F._merge_face(people, {"box": (104, 102, 80, 80)}, ("OWNER", 82, 0.18))
check("same face, better answer wins", people[0][1][0], "OWNER")
check("and it stayed one person", len(people), 1)

F._merge_face(people, {"box": (500, 300, 80, 80)}, ("OTHER", 70, 0.30))
check("a face somewhere else is a different person", len(people), 2)

people = [[{"box": (100, 100, 80, 80)}, ("OWNER", 95, 0.05)]]
F._merge_face(people, {"box": (100, 100, 80, 80)}, ("OTHER", 50, 0.50))
check("a WORSE second answer never overwrites a good one",
      people[0][1][0], "OWNER")

print("\nenrolling watches him move, and won't be fooled mid-sweep")
seen_by_sweep = []


def fake_camera(*looks):
    """Hand the sweep a scripted series of faces, one per grab."""
    queue = list(looks)

    def grab():
        return queue.pop(0) if queue else None
    return grab


def run_sweep(db, anchor, looks):
    """Drive _sweep against scripted faces instead of a real camera."""
    real_frame, real_faces, real_sleep = F.get_frame, F._faces_in, __import__("time").sleep
    queue = list(looks)
    F.get_frame = lambda: (queue[0] if queue else None)

    def fake_faces_in(frame, lift=False):
        if not queue:
            return []
        vec = queue.pop(0)
        return [{"embedding": vec, "box": (10, 10, 90, 90)}]

    F._faces_in = fake_faces_in
    F.time.sleep = lambda s: None
    ticks = [0.0]

    def clock():
        ticks[0] += 1.0
        return ticks[0]
    real_time = F.time.time
    F.time.time = clock
    try:
        return F._sweep("OWNER", db, anchor)
    finally:
        F.get_frame, F._faces_in = real_frame, real_faces
        F.time.sleep, F.time.time = real_sleep, real_time


db = fresh(BASE_FACE)
added = run_sweep(db, BASE_FACE,
                  [sideways(1, 0.6), sideways(2, 0.6), sideways(3, 0.6)])
check("different angles of him are collected", added, 3)
check("and stored", len(db["OWNER"]["embeddings"]), 4)

db = fresh(BASE_FACE)
added = run_sweep(db, BASE_FACE, [BASE_FACE, BASE_FACE, BASE_FACE])
check("sitting perfectly still adds nothing", added, 0)

db = fresh(BASE_FACE)
stranger = unit(0, 1, 0, 0, 0)
added = run_sweep(db, BASE_FACE, [stranger, stranger, sideways(1, 0.6)])
check("someone walking past mid-sweep is NOT enrolled as him", added, 1)
check("only his own look was kept", len(db["OWNER"]["embeddings"]), 2)

db = fresh(BASE_FACE)
added = run_sweep(db, BASE_FACE, [])
check("an empty room during the sweep is harmless", added, 0)

print("\nthe threshold covers his own variation")
check("a face 0.60 away is now recognised, where 0.55 rejected it",
      F.MATCH_THRESHOLD > 0.60, True)
check("but it stays well clear of a different person",
      F.MATCH_THRESHOLD < 0.78, True)
check("learning is still far stricter than naming",
      F.LEARN_THRESHOLD < F.MATCH_THRESHOLD / 2, True)

print("\nthe deadlock that made every face UNKNOWN forever")
# identify(wait=False) is what the live tracker and the room guard use. It
# used to give up whenever the models weren't warm, without ever starting
# them warming — and nothing else did either unless the dashboard camera
# page happened to be open. So recognition simply never ran, and looked
# from the outside exactly like a face it couldn't place.
was_ready, was_warming = F.ready, F._warming
started = []
real_thread = F.threading.Thread


class FakeThread:
    def __init__(self, target=None, daemon=None, **kw):
        started.append(target)

    def start(self):
        pass


try:
    F.ready = False
    F._warming = False
    F.threading.Thread = FakeThread
    out = F.identify(frame=None, wait=False)
    check("a caller that can't wait still gets an instant empty answer", out, [])
    check("but it kicked the models off loading instead of giving up",
          len(started), 1)

    started.clear()
    F.identify(frame=None, wait=False)
    check("and it doesn't pile up a thread per frame", len(started), 0)

    started.clear()
    F._warming = False
    F.ready = True
    F.identify(frame=None, wait=False)
    check("once warm it never warms again", len(started), 0)
finally:
    F.threading.Thread = real_thread
    F.ready, F._warming = was_ready, was_warming

print("\nbrightness reading")
try:
    check("black reads as dark",
          F.brightness(np.zeros((10, 10, 3), dtype=np.uint8)) < F.DARK_ENOUGH, True)
    check("white does not",
          F.brightness(np.full((10, 10, 3), 255, dtype=np.uint8)) < F.DARK_ENOUGH,
          False)
except Exception as bad:
    print("  FAIL brightness blew up:", bad)
    failed += 1

print(f"\n{passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
