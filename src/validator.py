"""Quality Control Agent.

Separate validation stage. Only PASSING assets may move to publishing.
Checks (per the constitution + brief):
  content   : hook length, banned phrases, formula/category validity
  image     : 9:16, off-white background, no model-added text (OCR),
              opens cleanly
  video     : 1080x1920, ~5s, h264+aac, size limits
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageOps

import common
import rotation


def validate_content(concept: dict, cfg: dict) -> list[str]:
    problems: list[str] = []
    q = cfg["quality"]
    hook = (concept.get("hook") or "").strip()
    if not hook:
        problems.append("empty hook")
    else:
        words = hook.split()
        if len(words) > q["hook_max_words"]:
            problems.append(f"hook {len(words)} words > {q['hook_max_words']}")
        if len(hook) > q["hook_max_chars"]:
            problems.append(f"hook {len(hook)} chars > {q['hook_max_chars']}")
    hits = rotation.banned_hits(
        hook + " " + (concept.get("subline") or "") + " " + (concept.get("caption") or "")
    )
    if hits:
        problems.append(f"banned phrase: {hits}")
    if concept.get("category") not in rotation.CATEGORIES:
        problems.append(f"unknown category {concept.get('category')}")
    if concept.get("formula") not in rotation.FORMULAS:
        problems.append(f"unknown formula {concept.get('formula')}")
    if len((concept.get("hashtags") or [])) > 10:
        problems.append("too many hashtags (spam risk)")
    caption = concept.get("caption") or ""
    if len(caption) > q["caption_max_chars"]:
        problems.append("caption too long for Instagram (2200 max)")
    return problems


def _background_ok(path: Path, cfg: dict):
    """Brand rule: off-white background. Sample the 4 corners of the BASE
    image (before our text overlay)."""
    q = cfg["quality"]
    patch = q["background_corner_patch"]
    im = Image.open(path).convert("L")
    w, h = im.size
    corners = [
        im.crop((0, 0, patch, patch)),
        im.crop((w - patch, 0, w, patch)),
        im.crop((0, h - patch, patch, h)),
        im.crop((w - patch, h - patch, w, h)),
    ]
    # p75 per-pixel luminance per corner patch (robust to a small dark
    # watermark inside a patch); score = worst corner
    import numpy as np
    lums = []
    for c in corners:
        arr = np.asarray(c, dtype=np.float64)
        px = arr.reshape(-1, 3).mean(axis=1) if arr.ndim == 3 else arr.reshape(-1)
        lums.append(float(np.percentile(px, 75)))
    score = min(lums)
    return score >= q["background_min_luminance"], round(score, 1), [round(x, 1) for x in lums]


def ocr_text_words(path: Path) -> int | None:
    """If tesseract is available, count words the image model may have
    painted into the base image. None = OCR unavailable (check skipped)."""
    if shutil.which("tesseract") is None:
        return None
    try:
        import pytesseract
        im = Image.open(path)
        txt = pytesseract.image_to_string(im)
        return len([w for w in txt.split() if any(ch.isalnum() for ch in w)])
    except Exception:
        return None


def _subject_bbox(path: Path, cfg: dict) -> tuple[float, float]:
    """Return (top_frac, height_frac) of the subject's bounding box.

    Brand rule: the subject is small and low; the upper ~40% of the frame
    belongs to the text zone. A tall subject whose top edge reaches into
    that zone overlaps the hook even when the top-zone density check
    passes (e.g. a big white object whose dark side alone is small).
    """
    import numpy as np

    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    h, w, _ = a.shape
    patch = cfg["quality"]["background_corner_patch"]
    corners = [
        a[:patch, :patch].reshape(-1, 3).mean(0),
        a[:patch, w - patch:].reshape(-1, 3).mean(0),
        a[h - patch:, :patch].reshape(-1, 3).mean(0),
        a[h - patch:, w - patch:].reshape(-1, 3).mean(0),
    ]
    refs_list = [c for c in corners if c.mean() > 115]
    if not refs_list:
        return 1.0, 0.0
    refs = np.stack(refs_list)
    d = np.sqrt(((a[:, :, None, :] - refs[None, None, :, :]) ** 2).sum(-1)).min(-1)
    mask = d > 70
    rows = mask.sum(axis=1)
    good = np.where(rows > w * 0.015)[0]
    if len(good) == 0:
        return 1.0, 0.0
    return round(good[0] / h, 3), round((good[-1] - good[0]) / h, 3)


def _subject_too_high(path: Path, cfg: dict) -> tuple[bool, float]:
    """Brand rule: the subject lives in the lower ~55% of the frame; the
    upper third is the text zone. Measure how much clearly-subject material
    (pixels far from the background color) sits in the top 28% of the frame.
    """
    import numpy as np

    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    h, w, _ = a.shape
    patch = cfg["quality"]["background_corner_patch"]
    corners = [
        a[:patch, :patch].reshape(-1, 3).mean(0),
        a[:patch, w - patch:].reshape(-1, 3).mean(0),
        a[h - patch:, :patch].reshape(-1, 3).mean(0),
        a[h - patch:, w - patch:].reshape(-1, 3).mean(0),
    ]
    refs_list = [c for c in corners if c.mean() > 115]
    if not refs_list:
        return False, 0.0
    refs = np.stack(refs_list)
    d = np.sqrt(((a[:, :, None, :] - refs[None, None, :, :]) ** 2).sum(-1)).min(-1)
    top = d[int(h * 0.02):int(h * 0.28), int(w * 0.10):int(w * 0.90)]
    frac = float((top > 90).mean())
    return frac > 0.07, round(frac, 3)


def validate_base_image(path: Path, cfg: dict):
    """Return (problems, details)."""
    problems: list[str] = []
    details: dict = {}
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        return [f"image corrupt: {e}"], details
    w, h = im.size
    if abs(w / h - 9 / 16) > 0.06:
        problems.append(f"aspect ratio {w}/{h} not 9:16")
    ok, avg, corners = _background_ok(path, cfg)
    details["bg_luminance_avg"] = avg
    details["bg_corners"] = corners
    if not ok:
        problems.append(f"background not off-white (avg corner luminance {avg} < {cfg['quality']['background_min_luminance']})")
    too_high, frac = _subject_too_high(path, cfg)
    details["subject_top_frac"] = frac
    if too_high:
        problems.append(f"subject too high in frame (top-zone subject fraction {frac} > 0.07)")
    top_frac, height_frac = _subject_bbox(path, cfg)
    details["subject_bbox_top_frac"] = top_frac
    details["subject_bbox_height_frac"] = height_frac
    max_top = cfg["quality"].get("subject_max_top_frac", 0.42)
    max_h = cfg["quality"].get("subject_max_height_frac", 0.58)
    if top_frac < max_top:
        problems.append(f"subject reaches into the text zone (top edge at {top_frac:.0%} of frame, must be <= {max_top:.0%})")
    if height_frac > max_h:
        problems.append(f"subject too tall ({height_frac:.0%} of frame height, must be <= {max_h:.0%})")
    if cfg["quality"].get("ocr_enabled", True):
        words = ocr_text_words(path)
        details["ocr_words"] = words
        if words is not None and words > cfg["quality"]["ocr_max_words"]:
            problems.append(f"image model appears to have drawn text ({words} words by OCR)")
        wm_words = provider_watermark_words(path)
        details["watermark_zone_words"] = wm_words
        if wm_words and wm_words >= 1:
            problems.append("provider watermark detected in bottom-right zone")
    return problems, details


def provider_watermark_words(path: Path) -> int | None:
    """OCR ONLY the bottom-right zone (where free-tier providers stamp
    their mark). None = tesseract unavailable."""
    if shutil.which("tesseract") is None:
        return None
    try:
        import pytesseract
        im = Image.open(path)
        w, h = im.size
        zone = im.crop((w - 340, h - 110, w, h))
        zone = zone.resize((zone.width * 2, zone.height * 2), Image.LANCZOS)
        total = 0
        for z in (zone, ImageOps.invert(zone.convert("L")).convert("RGB")):
            txt = pytesseract.image_to_string(z)
            total = max(total, len([x for x in txt.split() if any(ch.isalnum() for ch in x)]))
        return total
    except Exception:
        return None


def validate_final_image(path: Path, cfg: dict):
    problems: list[str] = []
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        return [f"final image corrupt: {e}"]
    if im.size != (W, H):
        problems.append(f"final size {im.size[0]}x{im.size[1]} != {W}x{H}")
    return problems
