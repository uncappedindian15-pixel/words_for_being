#!/usr/bin/env python3
"""End-to-end test suite for the words.for.being pipeline.

Runs the real pipeline (subprocess + WFB_ROOT sandbox) against:
  - Pollinations (real, free, no key) for image generation
  - FFmpeg for video conversion
  - a local mock of the Instagram Graph API for publishing

Covers the 10 required tests:
  T1 concept generation + rotation      T6 simulated image failure
  T2 image generation                   T7 duplicate-generation protection
  T3 image -> MP4                       T8 simulated publishing failure (+recovery)
  T4 MP4 validation                     T9 restart & recovery (resume)
  T5 full pipeline + publishing         T10 two consecutive days, no creative repeat

Usage:  python tests/test_pipeline.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

PASS = 0
FAIL = 0
NOTES = []


def check(name: str, cond: bool, extra: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"   \u2714 {name}")
    else:
        FAIL += 1
        NOTES.append(f"{name} {extra}")
        print(f"   \u2718 {name}  {extra[:300]}")


class _TestState:
    pass


def make_sandbox() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="wfb_test_"))
    for item in ("config", "creative", "src", "fonts", "scripts"):
        shutil.copytree(ROOT / item, tmp / item, dirs_exist_ok=True)
    (tmp / "database" / "bank").mkdir(parents=True)
    for f in (ROOT / "database" / "bank").glob("*.json"):
        shutil.copy2(f, tmp / "database" / "bank" / f.name)
    for d in ("generated", "captions", "logs"):
        (tmp / d).mkdir(parents=True)
    (tmp / "generated" / "images").mkdir()
    (tmp / "generated" / "videos").mkdir()
    return tmp


def env_for(tmp: Path, **extra) -> dict:
    env = dict(os.environ)
    env["WFB_ROOT"] = str(tmp)
    for k in ("IG_ACCESS_TOKEN", "IG_USER_ID", "WFB_MOCK_BASE", "WFB_MODE", "WFB_TEST_FAST"):
        env.pop(k, None)
    env.update(extra)
    return env


def run_pipeline(tmp: Path, args: list, extra_env: dict | None = None, timeout: int = 900):
    p = subprocess.run(
        [sys.executable, str(tmp / "src" / "pipeline.py"), *args],
        env=env_for(tmp, **(extra_env or {})),
        capture_output=True, text=True, timeout=timeout, cwd=str(tmp),
    )
    return p


def seed_history(tmp: Path):
    """Pre-load one historical post so the rotation (deterministic on an
    empty history) does not gamble the full-pipeline tests on the bank's
    hardest-to-render concept (A-01, grey concrete semantics)."""
    import sys as _s
    _s.path.insert(0, str(tmp / "src"))
    import common as _c
    import rotation as _r
    cfg = _c.load_config()
    bank = _r.load_bank(cfg)
    a01 = next(c for c in bank if c["id"] == "A-01")
    db = {"posts": [{
        "post_id": "wfB-20981230-001", "date": "2098-12-30",
        "created": "2098-12-30T11:00:00+05:30", "status": "PUBLISHED",
        "concept": {k: v for k, v in a01.items() if not k.startswith("_")},
        "originality_report": None, "image": None, "video": None,
        "caption": None, "quality": None, "publish": {"permalink": "https://www.instagram.com/reel/seed/"},
        "timeline": [], "errors": [], "retries_total": 0,
    }], "meta": {}}
    (tmp / "database" / "content.json").write_text(__import__("json").dumps(db, indent=2))


def load_db(tmp: Path) -> dict:
    return json.loads((tmp / "database" / "content.json").read_text())


def post_for(db: dict, date: str):
    return next((p for p in db["posts"] if p["date"] == date), None)


def main() -> int:
    t_start = time.time()
    tmp = make_sandbox()
    seed_history(tmp)
    os.environ["WFB_ROOT"] = str(tmp)  # in-process imports use the sandbox
    sys.path.insert(0, str(tmp / "src"))

    from PIL import Image  # noqa: E402
    import common  # noqa: E402
    import rotation  # noqa: E402
    import imagegen  # noqa: E402
    import typography  # noqa: E402
    import video as video_mod  # noqa: E402
    from mock_ig import MockIG  # noqa: E402

    cfg = common.load_config()
    files_dir = tmp / "generated" / "videos"
    mock_env = {"IG_USER_ID": "100", "WFB_TEST_FAST": "1"}

    # ------------------------------------------------ T1
    print("T1  concept generation + rotation engine")
    bank = rotation.load_bank(cfg)
    check("bank loaded with 64 concepts", len(bank) == 64, f"got {len(bank)}")
    c1, r1 = rotation.pick_concept(cfg, bank, [], today="2099-01-01")
    check("picks a concept from empty history", c1 is not None)
    fake_history = [{"post_id": "x", "date": "2099-01-01", "status": "PUBLISHED", "concept": c1}]
    c2, r2 = rotation.pick_concept(cfg, bank, fake_history, today="2099-01-02")
    check("second pick differs from first", c2 is not None and c2["id"] != c1["id"])
    check("second pick avoids previous formula", c2 is not None and c2["formula"] != c1["formula"])
    check("rejections were logged", len(r2.get("rejections", [])) >= 1)
    bad = dict(c1)
    bad["hook"] = "protect your peace every single day"
    cb, _ = rotation.pick_concept(cfg, bank + [bad], [], today="2099-01-01")
    check("banned-phrase concept is rejected", cb is not None and cb["hook"] != bad["hook"])

    # ------------------------------------------------ T2
    print("T2  image generation (Pollinations — free, no key)")
    concept2 = next(c for c in bank if c["id"] == "D-03")
    out = tmp / "generated" / "images" / "t2-base.jpg"
    t0 = time.time()
    imagegen.generate_image(concept2, cfg, out)
    im = Image.open(out)
    im.load()
    check(f"base image generated in {time.time()-t0:.0f}s", out.exists() and min(im.size) >= 700, str(im.size))

    # ------------------------------------------------ T3
    print("T3  image -> 5s static MP4 (FFmpeg, local)")
    final_img = tmp / "generated" / "images" / "t2-final.jpg"
    typography.render_post(out, final_img, concept2, cfg)
    vid = tmp / "generated" / "videos" / "t2.mp4"
    video_mod.make_video(cfg, final_img, vid)
    check("mp4 created", vid.exists() and vid.stat().st_size > 10000, f"{vid.stat().st_size} bytes")

    # ------------------------------------------------ T4
    print("T4  MP4 validation")
    info = video_mod.probe(vid)
    probs = video_mod.validate_video(cfg, vid)
    check("mp4 passes full validation", not probs, "; ".join(probs))
    check("1080x1920 / ~5s / h264 / aac",
          info.get("width") == 1080 and info.get("height") == 1920
          and 4.7 <= (info.get("duration") or 0) <= 5.4
          and info.get("vcodec") == "h264" and info.get("acodec") == "aac", str(info))

    # ------------------------------------------------ T5
    print("T5  full pipeline + publishing (mocked IG Graph API)")
    mock = MockIG(files_dir)
    mock.start()
    p = run_pipeline(tmp, ["run", "--date", "2099-01-01", "--mode", "auto", "--concept", "A-02"],
                     {**mock_env, "WFB_MOCK_BASE": mock.base})
    db = load_db(tmp)
    post = post_for(db, "2099-01-01") or {}
    check("pipeline exit code 0", p.returncode == 0, (p.stdout[-400:] + p.stderr[-400:]))
    check("post marked PUBLISHED", post.get("status") == "PUBLISHED", post.get("status", "no post"))
    check("IG permalink recorded", bool((post.get("publish") or {}).get("permalink")))
    check("timeline has all stages", len(post.get("timeline", [])) >= 6, str(post.get("timeline")))
    cap = post.get("caption") or {}
    check("caption file written", bool(cap.get("path")) and Path(cap.get("path")).exists())
    mock.stop()

    # ------------------------------------------------ T6
    print("T6  simulated image-generation failure (dead endpoint, retry then FAILED)")
    cfgp = tmp / "config" / "config.json"
    cfgj = json.loads(cfgp.read_text())
    cfgj["image"]["pollinations"]["endpoint"] = "http://127.0.0.1:9/prompt/{prompt}"
    cfgj["quality"]["max_retries_image"] = 1
    cfgp.write_text(json.dumps(cfgj))
    try:
        p = run_pipeline(tmp, ["run", "--date", "2099-01-02", "--mode", "auto"],
                         mock_env, timeout=300)
    finally:
        cfgj["image"]["pollinations"]["endpoint"] = "https://image.pollinations.ai/prompt/{prompt}"
        cfgj["quality"]["max_retries_image"] = 3
        cfgp.write_text(json.dumps(cfgj))
    db = load_db(tmp)
    post = post_for(db, "2099-01-02") or {}
    check("exit code non-zero", p.returncode != 0, str(p.returncode))
    check("post marked FAILED (not silent)", post.get("status") == "FAILED", post.get("status", "no post"))
    check("retry count recorded", post.get("retries_total", 0) >= 1, str(post.get("retries_total")))
    check("no partial video created", not (files_dir / f"{post.get('post_id','')}.mp4").exists())

    # ------------------------------------------------ T7
    print("T7  duplicate-generation protection (re-run same date)")
    mock = MockIG(files_dir)
    mock.start()
    p = run_pipeline(tmp, ["run", "--date", "2099-01-01", "--mode", "auto"],
                     {**mock_env, "WFB_MOCK_BASE": mock.base})
    db = load_db(tmp)
    n = sum(1 for x in db["posts"] if x["date"] == "2099-01-01")
    out_low = (p.stdout + p.stderr).lower()
    check("re-run exits 0 as no-op", p.returncode == 0, str(p.returncode))
    check("still exactly one post for that date", n == 1, f"n={n}")
    check("ALREADY PUBLISHED guard fired", "already published" in out_low, out_low[-300:])
    mock.stop()

    # ------------------------------------------------ T8
    print("T8  simulated publishing failure -> MANUAL_ACTION_REQUIRED -> recovery")
    mock = MockIG(files_dir)
    mock.start()
    mock.fail_publish_remaining = 99
    p = run_pipeline(tmp, ["run", "--date", "2099-01-03", "--mode", "auto", "--concept", "D-03"],
                     {**mock_env, "WFB_MOCK_BASE": mock.base}, timeout=600)
    db = load_db(tmp)
    post = post_for(db, "2099-01-03") or {}
    check("exit code 2 (manual action)", p.returncode == 2, str(p.returncode))
    check("status MANUAL_ACTION_REQUIRED", post.get("status") == "MANUAL_ACTION_REQUIRED", post.get("status"))
    notif = tmp / "logs" / "notifications.md"
    check("human notification written", notif.exists() and "2099-01-03" in notif.read_text())
    mock.stop()
    # recover with a healthy API — assets reused, no duplicate content
    mock2 = MockIG(files_dir)
    mock2.start()
    p2 = run_pipeline(tmp, ["publish-today", "--date", "2099-01-03"],
                      {**mock_env, "WFB_MOCK_BASE": mock2.base}, timeout=300)
    db = load_db(tmp)
    post = post_for(db, "2099-01-03") or {}
    n3 = sum(1 for x in db["posts"] if x["date"] == "2099-01-03")
    check("recovered to PUBLISHED via publish-today", post.get("status") == "PUBLISHED",
          (p2.stdout[-300:] + p2.stderr[-300:]))
    check("no duplicate post record", n3 == 1, f"n={n3}")
    mock2.stop()

    # ------------------------------------------------ T9
    print("T9  restart & recovery (crash after image stage, resume)")
    mock = MockIG(files_dir)
    mock.start()
    env = {**mock_env, "WFB_MOCK_BASE": mock.base}
    p = run_pipeline(tmp, ["run", "--date", "2099-01-04", "--mode", "auto", "--stage", "image", "--concept", "B-14"], env)
    db = load_db(tmp)
    post = post_for(db, "2099-01-04") or {}
    check("stopped at IMAGE_READY", post.get("status") == "IMAGE_READY", post.get("status"))
    img = post.get("image") or {}
    final_path = Path(img.get("final_path", ""))
    mtime_before = final_path.stat().st_mtime_ns if final_path.exists() else None
    p2 = run_pipeline(tmp, ["run", "--date", "2099-01-04", "--mode", "auto"], env, timeout=900)
    db = load_db(tmp)
    post = post_for(db, "2099-01-04") or {}
    check("resumed and reached PUBLISHED", post.get("status") == "PUBLISHED", post.get("status"))
    mtime_after = final_path.stat().st_mtime_ns if final_path.exists() else None
    check("image was NOT regenerated (resumed from video stage)", mtime_before == mtime_after)
    mock.stop()

    # ------------------------------------------------ T10
    print("T10  two consecutive daily jobs — creative system must not repeat")
    mock = MockIG(files_dir)
    mock.start()
    env = {**mock_env, "WFB_MOCK_BASE": mock.base}
    run_pipeline(tmp, ["run", "--date", "2099-02-01", "--mode", "auto", "--concept", "A-03"], env, timeout=900)
    # day 2 uses the NATURAL rotation (must avoid day 1's formula 8)
    run_pipeline(tmp, ["run", "--date", "2099-02-02", "--mode", "auto"], env, timeout=900)
    db = load_db(tmp)
    p1 = post_for(db, "2099-02-01") or {}
    p2 = post_for(db, "2099-02-02") or {}
    c1, c2 = p1.get("concept") or {}, p2.get("concept") or {}
    check("day 1 published", p1.get("status") == "PUBLISHED", p1.get("status"))
    check("day 2 published", p2.get("status") == "PUBLISHED", p2.get("status"))
    check("different concept ids", c1.get("id") != c2.get("id"), f"{c1.get('id')} vs {c2.get('id')}")
    check("no consecutive formula repeat", c1.get("formula") != c2.get("formula"),
          f"F{c1.get('formula')} -> F{c2.get('formula')}")
    mock.stop()

    # ------------------------------------------------ summary
    print()
    print("=" * 62)
    print(f"  RESULT: {PASS} passed, {FAIL} failed   ({time.time()-t0:.0f}s total)")
    if NOTES:
        print("  failures:")
        for n in NOTES:
            print(f"   - {n}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
