"""Object detection: names the things the desk webcam can see right now, using
a small, fully-local SSD MobileNet-v1 model (COCO, run through onnxruntime —
the same engine already used for TARS's voice). Nothing leaves the PC."""
import sys
from pathlib import Path

DESCRIPTION = ("Detect and NAME objects the desk webcam can see right now — people, "
               "cars, animals, furniture, everyday items. E.g. 'what objects do you "
               "see', 'detect objects', 'what's in front of the camera'. NOT for "
               "naming known people (that's who_is_this) and NOT for open-ended "
               "scene questions (that's the camera skill).")
ARGS = {}

_MODEL_PATH = Path(__file__).parent / "ssd_mobilenet_v1_10.onnx"
_CONFIDENCE = 0.5

# TF/COCO's 90-slot label map: ids skip a few numbers (12, 26, 29, 30, 45, 66,
# 68, 69, 71, 83 are unused) — this is the standard mapping for this model.
_COCO_NAMES = {
    1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane",
    6: "bus", 7: "train", 8: "truck", 9: "boat", 10: "traffic light",
    11: "fire hydrant", 13: "stop sign", 14: "parking meter", 15: "bench",
    16: "bird", 17: "cat", 18: "dog", 19: "horse", 20: "sheep", 21: "cow",
    22: "elephant", 23: "bear", 24: "zebra", 25: "giraffe", 27: "backpack",
    28: "umbrella", 31: "handbag", 32: "tie", 33: "suitcase", 34: "frisbee",
    35: "skis", 36: "snowboard", 37: "sports ball", 38: "kite",
    39: "baseball bat", 40: "baseball glove", 41: "skateboard",
    42: "surfboard", 43: "tennis racket", 44: "bottle", 46: "wine glass",
    47: "cup", 48: "fork", 49: "knife", 50: "spoon", 51: "bowl",
    52: "banana", 53: "apple", 54: "sandwich", 55: "orange", 56: "broccoli",
    57: "carrot", 58: "hot dog", 59: "pizza", 60: "donut", 61: "cake",
    62: "chair", 63: "couch", 64: "potted plant", 65: "bed",
    67: "dining table", 70: "toilet", 72: "tv", 73: "laptop", 74: "mouse",
    75: "remote", 76: "keyboard", 77: "cell phone", 78: "microwave",
    79: "oven", 80: "toaster", 81: "sink", 82: "refrigerator", 84: "book",
    85: "clock", 86: "vase", 87: "scissors", 88: "teddy bear",
    89: "hair drier", 90: "toothbrush",
}

_session = None  # loaded once, reused on every call


def _load_session():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(str(_MODEL_PATH),
                                         providers=["CPUExecutionProvider"])
    return _session


def _plural(label: str, count: int) -> str:
    if count == 1:
        return f"a {label}"
    if label.endswith(("s", "x", "ch")):
        return f"{count} {label}es"
    return f"{count} {label}s"


def run(args: dict) -> str:
    import cv2

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from faces import get_frame  # stream-first: never disturbs a live feed

    frame = get_frame()
    if frame is None:
        return "The camera didn't answer. Is something else using it?"

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    sess = _load_session()
    boxes, classes, scores, num = sess.run(
        None, {"image_tensor:0": rgb[None, ...]})

    found = {}
    for cls_id, score in zip(classes[0], scores[0]):
        if score < _CONFIDENCE:
            continue
        name = _COCO_NAMES.get(int(cls_id))
        if name:
            found[name] = found.get(name, 0) + 1

    if not found:
        return "I don't recognise anything in view right now."
    parts = [_plural(label, count) for label, count in found.items()]
    return "I can see " + ", ".join(parts) + "."
