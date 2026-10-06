"""Photo mode: turn a real player's headshot into a cartoon-shaded head that drops into the illustrated uniform.

Pipeline: find the face (YuNet, with a Haar-cascade fallback) -> rotate and scale so the eyes are level at a fixed
distance -> cut the head out (the photo's own transparency if it has one, otherwise GrabCut) -> fade out below the
chin -> cel-shade (bilateral smoothing, banded lighting, soft ink lines) -> sample the skin color so the drawn neck
matches.

Needs numpy and opencv-python-headless (`pip install simface[photo]`).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from importlib import resources

from .colors import darken, to_hex

# Working resolution: distance between the eyes in the processed image, in pixels.
EYE_DIST = 110


@dataclass
class PhotoHead:
    png: bytes  # RGBA cut-out, eyes level at (eye_x, eye_y), EYE_DIST apart
    width: int
    height: int
    eye_x: float
    eye_y: float
    skin: str  # cheek color, slightly shaded, for the drawn neck
    head_half_width: float  # head half-width at forehead height, px (sizes the cap)
    head_top: float  # topmost head/hair pixel, px
    chin_y: float  # px
    neck_half_width: float  # px, just below the chin


class NoFaceFound(Exception):
    pass


def _cv():
    try:
        import cv2
        import numpy as np
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise RuntimeError("photo mode needs numpy and opencv: pip install opencv-python-headless numpy") from e
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:
        pass
    return cv2, np


def _decode(data: bytes):
    cv2, np = _cv()
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        # Formats OpenCV can't read (e.g. some WebP/AVIF builds): go through Pillow.
        from PIL import Image

        pil = Image.open(io.BytesIO(data)).convert("RGBA")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGBA2BGRA)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    if img.dtype != np.uint8:
        img = (img / 256).astype(np.uint8)
    return img


def find_face(bgr) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float] | None]:
    """Eye centers (image-left eye first) of the most prominent face, plus the bottom-center of the face box
    (roughly the chin) when the detector provides one."""
    cv2, np = _cv()
    h, w = bgr.shape[:2]
    k = min(1.0, 800 / max(h, w))
    small = cv2.resize(bgr, (max(1, int(w * k)), max(1, int(h * k)))) if k < 1 else bgr
    model = resources.files("simface").joinpath("data/face_detection_yunet_2023mar.onnx")
    with resources.as_file(model) as model_path:
        det = cv2.FaceDetectorYN.create(str(model_path), "", (small.shape[1], small.shape[0]), 0.6, 0.3, 50)
        _, faces = det.detect(small)
    if faces is not None and len(faces):
        f = max(faces, key=lambda r: r[14] * r[2] * r[3])
        a, b = (f[4] / k, f[5] / k), (f[6] / k, f[7] / k)
        chin = ((f[0] + f[2] / 2) / k, (f[1] + f[3]) / k)
        return ((a, b) if a[0] <= b[0] else (b, a)) + (chin,)
    # Fallback: frontal-face Haar cascade, eyes at typical positions inside the box.
    # (OpenCV 5 moved the cascades out of the main package; then YuNet is all there is.)
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        raise NoFaceFound("no face found in photo")
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    boxes = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
    if len(boxes) == 0:
        raise NoFaceFound("no face found in photo")
    x, y, bw, bh = max(boxes, key=lambda r: r[2] * r[3])
    ey = (y + bh * 0.4) / k
    return ((x + bw * 0.3) / k, ey), ((x + bw * 0.7) / k, ey), ((x + bw / 2) / k, (y + bh * 1.02) / k)


def _has_alpha(bgra) -> bool:
    a = bgra[:, :, 3]
    return bool((a < 250).mean() > 0.02)


def prepare_photo(data: bytes, toon: float = 0.7) -> PhotoHead:
    """Process raw image bytes (PNG/JPEG/WebP) into a PhotoHead. Raises NoFaceFound."""
    cv2, np = _cv()
    src = _decode(data)
    bgr = np.ascontiguousarray(src[:, :, :3])
    (lx, ly), (rx, ry), chin_src = find_face(bgr)

    d = EYE_DIST
    W, H = int(d * 4.2), int(d * 5.4)
    eye_x, eye_y = W / 2, d * 2.6
    angle = math.degrees(math.atan2(ry - ly, rx - lx))
    scale = d / max(1.0, math.hypot(rx - lx, ry - ly))
    M = cv2.getRotationMatrix2D(((lx + rx) / 2, (ly + ry) / 2), angle, scale)
    M[0, 2] += eye_x - (lx + rx) / 2
    M[1, 2] += eye_y - (ly + ry) / 2
    img = cv2.warpAffine(bgr, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    def ellipse(cx, cy, ax, ay):
        return ((xx - cx) / ax) ** 2 + ((yy - cy) / ay) ** 2

    if _has_alpha(src):
        fg = cv2.warpAffine(src[:, :, 3], M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0).astype(np.float32) / 255
    else:
        mask = np.full((H, W), cv2.GC_PR_BGD, np.uint8)
        mask[ellipse(eye_x, eye_y - 0.3 * d, 1.5 * d, 2.3 * d) <= 1] = cv2.GC_PR_FGD
        mask[ellipse(eye_x, eye_y + 0.5 * d, 0.7 * d, 1.15 * d) <= 1] = cv2.GC_FGD
        edge = int(d * 0.12)
        mask[:edge, :] = cv2.GC_BGD
        mask[: int(eye_y), :edge] = cv2.GC_BGD
        mask[: int(eye_y), -edge:] = cv2.GC_BGD
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(img, mask, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
        fg = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
        # Keep the blob connected to the face and fill small holes.
        n, labels = cv2.connectedComponents(fg)
        if n > 2:
            fg = (labels == labels[int(eye_y + 0.5 * d), int(eye_x)]).astype(np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)).astype(np.float32)
        fg = cv2.GaussianBlur(fg, (0, 0), 1.2)

    # Only the head: an oval around it, fading out below the chin so the drawn neck takes over.
    chin = eye_y + 1.7 * d
    if chin_src is not None:
        cy = M[1, 0] * chin_src[0] + M[1, 1] * chin_src[1] + M[1, 2]
        chin = float(np.clip(cy, eye_y + 1.35 * d, eye_y + 2.1 * d))
    oval = np.clip((1.0 - ellipse(eye_x, eye_y - 0.25 * d, 1.85 * d, chin - eye_y + 0.75 * d)) * 6, 0, 1)
    # Detector boxes end a little below the real chin, so the fade starts just above it.
    fade = np.clip(1 - (yy - chin + 0.1 * d) / (0.28 * d), 0, 1)
    alpha = np.clip(fg * oval * fade, 0, 1)

    out = _toon(img, toon) if toon > 0 else img
    neck_row = fg[min(H - 1, int(chin + 0.3 * d))]
    neck_cols = np.where(neck_row[int(eye_x - 1.2 * d): int(eye_x + 1.2 * d)] > 0.5)[0]
    neck_half = float(len(neck_cols) / 2) if len(neck_cols) else 0.6 * d
    skin = darken(_sample_skin(out, fg, eye_x, eye_y, d), 0.1)
    rows = np.where(alpha.max(axis=1) > 0.5)[0]
    head_top = float(rows[0]) if len(rows) else eye_y - 2.2 * d
    brow_row = alpha[int(eye_y - 0.9 * d)]
    cols = np.where(brow_row > 0.5)[0]
    half = float(max(eye_x - cols[0], cols[-1] - eye_x)) if len(cols) else 1.15 * d

    rgba = np.dstack([cv2.cvtColor(out, cv2.COLOR_BGR2RGB), (alpha * 255).astype(np.uint8)])
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return PhotoHead(buf.getvalue(), W, H, eye_x, eye_y, skin, min(half, 1.6 * d), head_top, chin,
                     float(np.clip(neck_half, 0.45 * d, 0.95 * d)))


def _toon(bgr, strength: float):
    """Cel-shaded look that keeps the likeness: smooth skin, banded light, soft ink lines, a little more color."""
    cv2, np = _cv()
    smooth = cv2.bilateralFilter(bgr, 9, 50, 7)
    smooth = cv2.bilateralFilter(smooth, 9, 50, 7)
    lab = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0]
    step = 255 / 8
    banded = np.round(L / step) * step
    # Soft bands: pull lightness toward the band center instead of a hard posterize.
    lab[:, :, 0] = L + (banded - L) * 0.55
    lab[:, :, 1:] = 128 + (lab[:, :, 1:] - 128) * 1.15
    toon = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR).astype(np.float32)
    gray = cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    dog = cv2.GaussianBlur(gray, (0, 0), 1.0) - cv2.GaussianBlur(gray, (0, 0), 1.8)
    ink = np.clip((-dog - 0.006) * 28, 0, 1)
    toon *= (1 - 0.6 * ink)[:, :, None]
    out = bgr.astype(np.float32) * (1 - strength) + toon * strength
    return np.clip(out, 0, 255).astype(np.uint8)


def _sample_skin(bgr, alpha, eye_x: float, eye_y: float, d: float) -> str:
    """Median color of both cheeks (falls back to the whole image)."""
    _, np = _cv()
    r = max(2, int(d * 0.1))
    samples = []
    for cx, cy in ((eye_x - 0.5 * d, eye_y + 0.6 * d), (eye_x + 0.5 * d, eye_y + 0.6 * d)):
        x0, y0 = int(cx) - r, int(cy) - r
        patch = bgr[y0 : y0 + 2 * r, x0 : x0 + 2 * r]
        a = alpha[y0 : y0 + 2 * r, x0 : x0 + 2 * r]
        if patch.size:
            samples.append(patch[a > 0.5])
    px = np.concatenate([s for s in samples if len(s)]) if any(len(s) for s in samples) else bgr.reshape(-1, 3)
    b, g, r_ = np.median(px, axis=0)
    return to_hex((r_, g, b))
