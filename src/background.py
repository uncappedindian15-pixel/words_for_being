"""Background normalizer — makes free-model output match the brand.

Strategy (chosen for robustness over cleverness):
  1. Flood fill from the border with a local-continuity rule to capture
     the background region (stops at the subject silhouette).
  2. If the render already has a near-white background (corners >= 185):
     LIFT the captured background to the exact brand off-white with a
     texture-preserving remap (grain/vignette survive). At near-white
     the capture can never hurt the subject (same color family).
  3. Paint over the provider watermark zone (bottom-right) when it is
     background — only for near-white renders, so no visible patch.
  4. Genuinely grey/dark renders are left untouched: the QC gate rejects
     them and the pipeline retries with a stronger prompt and a new
     seed. No half-baked recolors, no sticker artifacts.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

import common


def _hex_to_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64)


def flood_capture(a: np.ndarray, delta: int = 14, min_light: float = 105.0):
    """Boolean mask of the background: light region connected to the border
    through small local color steps."""
    h, w, _ = a.shape
    ai = a.astype(np.int16)
    mean = a.mean(axis=2)
    visited = np.zeros((h, w), dtype=bool)
    q = deque()

    def seed(y, x):
        if not visited[y, x] and mean[y, x] > min_light:
            visited[y, x] = True
            q.append(y * w + x)

    for x in range(0, w, 2):
        seed(0, x); seed(1, x); seed(h - 2, x); seed(h - 1, x)
    for y in range(0, h, 2):
        seed(y, 0); seed(y, 1); seed(y, w - 2); seed(y, w - 1)
    if not q:
        return None

    d2 = delta * delta * 3
    while q:
        idx = q.popleft()
        y, x = divmod(idx, w)
        r, g, b = ai[y, x]
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if ny < 0 or ny >= h or nx < 0 or nx >= w or visited[ny, nx]:
                continue
            pr, pg, pb = int(ai[ny, nx][0]), int(ai[ny, nx][1]), int(ai[ny, nx][2])
            if (pr - int(r)) ** 2 + (pg - int(g)) ** 2 + (pb - int(b)) ** 2 <= d2 and mean[ny, nx] > min_light:
                visited[ny, nx] = True
                q.append(ny * w + nx)
    return visited


def normalize_background(path: Path, cfg: dict) -> Path:
    path = Path(path)
    im = Image.open(path).convert("RGB")
    a = np.asarray(im, dtype=np.float64)
    h, w, _ = a.shape

    if a.mean() < 90:
        return path  # dark image: leave for QC to reject

    patch = cfg["quality"]["background_corner_patch"]
    patches = [
        a[:patch, :patch],
        a[:patch, w - patch:],
        a[h - patch:, :patch],
        a[h - patch:, w - patch:],
    ]
    # p75 per-pixel luminance per corner patch: robust to a small dark
    # watermark sitting inside a corner (same statistic QC uses)
    corner_lums = [np.percentile(pt.reshape(-1, 3).mean(axis=1), 75) for pt in patches]
    corner_score = min(corner_lums)

    brand_bg = _hex_to_rgb(cfg["canvas"]["background"])

    # provider watermark zone (bottom-right): erase BEFORE the lift gate so
    # even a borderline-grey render loses the provider mark. Paint with the
    # local tone (invisible patch) unless the render is near-white.
    zh, zw = 130, 420
    zone = a[h - zh:, w - zw:]
    zone_lum = np.percentile(zone.reshape(-1, 3).mean(axis=1), 75)
    if abs(zone_lum - corner_score) < 45:
        zone_med = np.median(zone.reshape(-1, 3), axis=0)
        paint = np.asarray(brand_bg if corner_score >= 180 else zone_med, dtype=np.float64)
        # feathered blend: solid paint at the zone center fading to the
        # original at the edges, so the patch seam is invisible
        f = 30
        m = np.ones((zh, zw), dtype=np.float64)
        for i in range(f):
            g = i / f
            m[i, :] = np.minimum(m[i, :], g)
            m[zh - 1 - i, :] = np.minimum(m[zh - 1 - i, :], g)
            m[:, i] = np.minimum(m[:, i], g)
            m[:, zw - 1 - i] = np.minimum(m[:, zw - 1 - i], g)
        a[h - zh:, w - zw:] = zone * (1 - m[..., None]) + paint * m[..., None]

    # lift the rest of the background to exact brand off-white — only when
    # near-white, where the flood capture can never hurt the subject
    if corner_score < 180:
        out = Image.fromarray(a.astype(np.uint8))
        out.save(path, "JPEG", quality=93)
        return path

    bg = flood_capture(a)
    if bg is None or bg.mean() < 0.12:
        return path
    bg_mean = a[bg].mean(axis=0)
    a[bg] = np.clip(brand_bg + (a[bg] - bg_mean) * 0.35, 0, 255)

    out = Image.fromarray(a.astype(np.uint8))
    out.save(path, "JPEG", quality=93)
    return path
