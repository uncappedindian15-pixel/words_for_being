"""Base image generation.

Provider 'pollinations' (default): free, no key, no signup.
  GET https://image.pollinations.ai/prompt/{prompt}?width=1080&height=1920
Provider 'local': ComfyUI on your own machine (optional, fully free).
Provider 'file': copy a pre-made image (testing / offline).

All typography is composited locally later — the model must NOT draw text.
"""
from __future__ import annotations

import io
import shutil
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image

import common


class ImageError(Exception):
    pass


def build_prompt(concept: dict, cfg: dict, extra: str = "") -> str:
    parts = [concept["image_prompt"].strip().rstrip(","), cfg["image"]["style_suffix"]]
    if extra:
        parts.append(extra)
    return ", ".join(parts) + ", " + cfg["image"]["negative_hint"]


def pollinations_url(cfg: dict, prompt: str, seed: int) -> str:
    q = cfg["image"]["pollinations"]
    base = q["endpoint"].replace("{prompt}", urllib.parse.quote(prompt, safe=""))
    params = {
        "width": q.get("width", 1080),
        "height": q.get("height", 1920),
        "model": q.get("model", "flux"),
        "nologo": "true" if q.get("nologo", True) else "false",
        "seed": seed,
    }
    return base + "?" + urllib.parse.urlencode(params)


def generate_image(concept: dict, cfg: dict, out_path: Path, seed: int | None = None, extra: str = "") -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seed = seed or (int(time.time()) % 100000)
    provider = cfg["image"]["provider"]

    if provider == "pollinations":
        url = pollinations_url(cfg, build_prompt(concept, cfg, extra), seed)
        r = requests.get(url, timeout=cfg["image"]["pollinations"]["timeout_seconds"])
        if r.status_code == 429:
            raise ImageError("pollinations rate-limited (HTTP 429) — wait 15s and retry")
        if r.status_code != 200:
            raise ImageError(f"pollinations HTTP {r.status_code}: {r.text[:200]}")
        img = Image.open(io.BytesIO(r.content))
        img.load()
        img.convert("RGB").save(out_path, "JPEG", quality=92)

    elif provider == "local":
        _local_comfyui(concept, cfg, out_path, extra)

    elif provider == "file":
        src = Path(cfg["image"].get("file_source", ""))
        if not src.exists():
            raise ImageError(f"file provider source missing: {src}")
        shutil.copyfile(src, out_path)

    else:
        raise ImageError(f"unknown image provider: {provider}")

    # sanity: must open and be big enough; normalize to exact canvas size
    # (free tiers may return e.g. 576x1024 at the right 9:16 ratio —
    #  upscaling a flat illustration is visually fine and deterministic)
    im = Image.open(out_path)
    im.load()
    w, h = im.size
    if min(w, h) < 400:
        raise ImageError(f"image too small: {w}x{h}")
    tw, th = cfg["canvas"]["width"], cfg["canvas"]["height"]
    if (w, h) != (tw, th):
        im = im.resize((tw, th), Image.LANCZOS)
        im.convert("RGB").save(out_path, "JPEG", quality=93)
    return out_path


def _local_comfyui(concept: dict, cfg: dict, out_path: Path, extra: str) -> None:
    """Optional local fallback. Requires ComfyUI running with a standard
    text-to-image workflow. Configure workflow JSON at
    scripts/comfyui_workflow.json with a placeholder node id 'PROMPT'.
    """
    import json
    url = cfg["image"]["local"]["comfyui_url"].rstrip("/")
    wf_path = common.ROOT / "scripts" / "comfyui_workflow.json"
    if not wf_path.exists():
        raise ImageError("local provider needs scripts/comfyui_workflow.json (ComfyUI workflow)")
    wf = json.loads(wf_path.read_text())
    for node in wf.values():
        if node.get("class_type") in ("CLIPTextEncode", "Prompt"):
            node.setdefault("inputs", {})["text"] = build_prompt(concept, cfg, extra)
    r = requests.post(f"{url}/prompt", json={"prompt": wf, "client_id": "wfb"}, timeout=30)
    if r.status_code != 200:
        raise ImageError(f"comfyui submit failed: {r.text[:200]}")
    pid = r.json()["prompt_id"]
    for _ in range(120):
        time.sleep(5)
        st = requests.get(f"{url}/history/{pid}", timeout=30).json()
        if pid in st:
            outputs = st[pid].get("outputs", {})
            for node_out in outputs.values():
                for img_file in node_out.get("images", []):
                    name = img_file.get("filename")
                    if name:
                        ir = requests.get(
                            f"{url}/view?filename={urllib.parse.quote(name)}"
                            f"&subfolder={urllib.parse.quote(img_file.get('subfolder',''))}"
                            f"&type={img_file.get('type','output')}",
                            timeout=60,
                        )
                        ir.raise_for_status()
                        Image.open(io.BytesIO(ir.content)).convert("RGB").save(out_path, "JPEG", quality=92)
                        return
            raise ImageError("comfyui finished but no image output found")
    raise ImageError("comfyui timed out after 10 minutes")
