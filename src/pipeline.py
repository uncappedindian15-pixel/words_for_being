#!/usr/bin/env python3
"""words.for.being — daily autonomous pipeline.

Stages (idempotent, resume from failure, never restart what is done):
  concept  -> image -> (QC) -> video -> (QC) -> caption -> publish

Usage:
  python src/pipeline.py run [--date YYYY-MM-DD] [--mode auto|safe] [--dry-run]
  python src/pipeline.py publish-today [--date YYYY-MM-DD]
  python src/pipeline.py status
  python src/pipeline.py dashboard
  python src/pipeline.py topup [--count N]
  python src/pipeline.py prune [--days N]

Exit codes: 0 = ok (published / safe-ready / no-op)
            1 = failed (logged, retryable next run)
            2 = manual action required
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

import common  # noqa: E402
import rotation  # noqa: E402
import imagegen  # noqa: E402
import background  # noqa: E402
import typography  # noqa: E402
import video  # noqa: E402
import validator  # noqa: E402
import publisher  # noqa: E402
import hosting  # noqa: E402
import dashboard  # noqa: E402

STAGES = ["concept", "image", "video", "caption", "publish"]

_FAST = os.environ.get("WFB_TEST_FAST") == "1"


def _sleep(s: float):
    time.sleep(1 if _FAST else s)


# ---------------------------------------------------------------- helpers
def _save(cfg, db, post):
    common.save_db(cfg, db)


def _tl(post, stage, msg, ok=True):
    post["timeline"].append({"stage": stage, "ok": ok, "ts": common.now_ist().isoformat(), "msg": msg})


def _new_post(cfg, db, date: str) -> dict:
    seq = 1 + sum(1 for p in db["posts"] if p["date"] == date)
    return {
        "post_id": common.make_post_id(date, seq),
        "date": date,
        "created": common.now_ist().isoformat(),
        "status": "QUEUED",
        "concept": None,
        "originality_report": None,
        "image": None,
        "video": None,
        "caption": None,
        "quality": None,
        "publish": None,
        "timeline": [],
        "errors": [],
        "retries_total": 0,
    }


def _caption_text(concept: dict) -> str:
    tags = " ".join(concept.get("hashtags") or [])
    return (concept.get("caption") or "").strip() + ("\n\n" + tags if tags else "")


def _public_video_url(cfg, post, vid: Path) -> str:
    mock = os.environ.get("WFB_MOCK_BASE")
    if mock:
        return f"{mock.rstrip('/')}/files/{vid.name}"
    # reuse a previously uploaded URL (idempotent resume / retry)
    prev = (post.get("publish") or {}).get("video_url")
    if prev:
        return prev
    return hosting.host_video(cfg, vid, logger)


def _notify(cfg, post, text):
    common.append_notification(
        cfg,
        f"{text}\n\n- post: `{post['post_id']}` (date {post['date']})\n"
        f"- stage reached: {post['status']}\n"
        f"- errors: {post['errors'][-3:] if post['errors'] else 'none logged'}\n"
        f"- see `dashboard.html` and `logs/pipeline.log`",
    )


# ---------------------------------------------------------------- stage: concept
def stage_concept(cfg, db, post, logger):
    if post["concept"]:
        logger.info(f"[{post['post_id']}] concept: already selected, keeping")
        return True
    bank = rotation.load_bank(cfg)
    forced = post.pop("_force_concept", None)
    if forced:
        concept = next((c for c in bank if c["id"] == forced), None)
        report = {"chosen": concept, "score": None, "cycle_reset": False,
                  "rejections": [], "candidates": len(bank), "errors": []}
        if concept is None:
            report["errors"] = [f"forced concept {forced} not found in bank"]
        else:
            logger.info(f"[{post['post_id']}] concept forced to {forced}")
    else:
        concept, report = rotation.pick_concept(cfg, bank, db["posts"], today=post["date"])
    if concept is None:
        post["status"] = "MANUAL_ACTION_REQUIRED"
        post["errors"].append("concept selection failed: " + "; ".join(report.get("errors", [])))
        _tl(post, "concept", "no original concept passed checks", ok=False)
        _notify(cfg, post, "🛑 Concept selection failed — every bank concept was rejected by originality checks.")
        return False
    problems = validator.validate_content(concept, cfg)
    if problems:
        post["status"] = "MANUAL_ACTION_REQUIRED"
        post["errors"].append("concept failed content QC: " + "; ".join(problems))
        _tl(post, "concept", f"content QC failed: {problems}", ok=False)
        _notify(cfg, post, "🛑 Selected concept failed content QC.")
        return False
    post["concept"] = {k: v for k, v in concept.items() if not k.startswith("_")}
    post["originality_report"] = report
    post["status"] = "QUEUED"
    _tl(post, "concept",
        f"selected {concept['id']} (cat {concept['category']} / formula {concept['formula']}: "
        f"{rotation.FORMULAS[concept['formula']]}, rejections={len(report['rejections'])})")
    # optional zero-cost bank top-up when the bank runs low (only if a free key exists)
    try:
        import llm_topup
        llm_topup.maybe_topup(cfg, bank, logger)
    except Exception as e:
        logger.warning(f"bank topup check failed (non-fatal): {e}")
    return True


# ---------------------------------------------------------------- stage: image
def stage_image(cfg, db, post, logger):
    img_dir = common.ROOT / cfg["paths"]["generated_images"]
    base = img_dir / f"{post['post_id']}-base.jpg"
    final = img_dir / f"{post['post_id']}.jpg"
    concept = post["concept"]

    if base.exists() and final.exists():
        logger.info(f"[{post['post_id']}] image: artifacts exist, skipping generation (resume)")
        if not post["image"]:
            post["image"] = {"path": str(base), "final_path": str(final), "provider": cfg["image"]["provider"], "retries": 0}
        post["status"] = "IMAGE_READY"
        return True

    post["status"] = "GENERATING"
    max_re = cfg["quality"]["max_retries_image"]
    base_seed = sum(ord(c) for c in post["post_id"]) % 100000
    last_err = None
    last_issues: list[str] = []
    for attempt in range(max_re + 1):
        extra = ""
        if attempt:
            extra = cfg["image"]["retry_extra_prompt"]
            dyn = []
            if any("background" in i for i in last_issues):
                dyn.append("the background must be bright white, absolutely not grey and not beige, not a grey studio")
            if any("subject too high" in i for i in last_issues):
                dyn.append("keep the object small and low, the entire upper third of the frame must be empty")
            if any("text zone" in i or "too tall" in i for i in last_issues):
                dyn.append("make the object much smaller, placed in the lower part of the frame, the upper half of the frame completely empty white")
            if dyn:
                extra += ", " + "; ".join(dyn)
        try:
            imagegen.generate_image(concept, cfg, base, seed=base_seed + attempt * 7919, extra=extra)
            background.normalize_background(base, cfg)
            problems, details = validator.validate_base_image(base, cfg)
            if problems:
                last_issues = problems
                bg_only = all(("background" in i or "luminance" in i) for i in problems)
                marginal = (attempt == max_re and bg_only
                            and (details.get("bg_luminance_avg") or 0) >= 172)
                if not marginal:
                    raise imagegen.ImageError("base image failed QC: " + "; ".join(problems))
                details["marginal_bg"] = True
                logger.warning(f"[{post['post_id']}] accepting MARGINAL render on last attempt "
                               f"(bg luminance {details.get('bg_luminance_avg')}); flagged in dashboard")
            typography.render_post(base, final, concept, cfg)
            fproblems = validator.validate_final_image(final, cfg)
            if fproblems:
                raise imagegen.ImageError("final image failed QC: " + "; ".join(fproblems))
            post["image"] = {"path": str(base), "final_path": str(final),
                             "provider": cfg["image"]["provider"], "retries": attempt, **details}
            post["status"] = "IMAGE_READY"
            _tl(post, "image", f"image ready (retries={attempt}, bg={details.get('bg_luminance_avg')}, ocr_words={details.get('ocr_words')})")
            return True
        except Exception as e:
            last_err = str(e)
            post["retries_total"] = post.get("retries_total", 0) + 1
            post["errors"].append(f"image attempt {attempt + 1}: {last_err}")
            _tl(post, "image", f"attempt {attempt + 1} failed: {last_err[:160]}", ok=False)
            if attempt < max_re:
                post["status"] = "RETRYING"
                logger.warning(f"[{post['post_id']}] image retry {attempt + 1}/{max_re}")
                if "rate-limited" in last_err or "429" in last_err:
                    time.sleep(20)  # respect provider throttle even in fast mode
                else:
                    _sleep(20 + attempt * 15)
    post["status"] = "FAILED"
    _notify(cfg, post, f"🛑 Image generation failed after {max_re + 1} attempts. Last error: {last_err}")
    return False


# ---------------------------------------------------------------- stage: video
def stage_video(cfg, db, post, logger):
    vid_dir = common.ROOT / cfg["paths"]["generated_videos"]
    vid = vid_dir / f"{post['post_id']}.mp4"
    final_img = Path(post["image"]["final_path"])

    if vid.exists():
        probs = video.validate_video(cfg, vid)
        if not probs:
            logger.info(f"[{post['post_id']}] video: exists and valid, skipping (resume)")
            if not post["video"]:
                post["video"] = {"path": str(vid), **video.probe(vid)}
            post["status"] = "VIDEO_READY"
            return True
        logger.warning(f"[{post['post_id']}] video exists but invalid ({probs}); regenerating")
        vid.unlink()

    max_re = cfg["quality"]["max_retries_video"]
    last_err = None
    for attempt in range(max_re + 1):
        try:
            video.make_video(cfg, final_img, vid)
            probs = video.validate_video(cfg, vid)
            if probs:
                raise video.VideoError("; ".join(probs))
            post["video"] = {"path": str(vid), **video.probe(vid)}
            post["status"] = "VIDEO_READY"
            _tl(post, "video", f"video ready: {post['video'].get('duration')}s {post['video'].get('width')}x{post['video'].get('height')} {post['video'].get('size_mb')}MB")
            return True
        except Exception as e:
            last_err = str(e)
            post["retries_total"] = post.get("retries_total", 0) + 1
            post["errors"].append(f"video attempt {attempt + 1}: {last_err}")
            _tl(post, "video", f"attempt {attempt + 1} failed: {last_err[:160]}", ok=False)
            if attempt < max_re:
                post["status"] = "RETRYING"
                _sleep(10)
    post["status"] = "FAILED"
    _notify(cfg, post, f"🛑 Video conversion failed after {max_re + 1} attempts. Last error: {last_err}")
    return False


# ---------------------------------------------------------------- stage: caption
def stage_caption(cfg, db, post, logger):
    cap_dir = common.ROOT / cfg["paths"]["captions"]
    cap_path = cap_dir / f"{post['post_id']}.txt"
    text = _caption_text(post["concept"])
    cap_path.write_text(text, encoding="utf-8")
    post["caption"] = {"path": str(cap_path), "text": text}
    post["quality"] = {
        "content": "PASS",
        "base_image": (post.get("image") or {}).get("bg_luminance_avg"),
        "ocr_words": (post.get("image") or {}).get("ocr_words"),
        "video": (post.get("video") or {}).get("duration"),
        "checked_at": common.now_ist().isoformat(),
    }
    post["status"] = "READY_TO_PUBLISH"
    _tl(post, "caption", f"caption ready ({len(text)} chars)")
    return True


# ---------------------------------------------------------------- stage: publish
def stage_publish(cfg, db, post, logger, force=False):
    if post["status"] == "PUBLISHED":
        logger.info(f"[{post['post_id']}] already published — no-op (duplicate protection)")
        return True
    mode = cfg["instagram"]["mode"]
    if mode == "safe" and not force:
        _tl(post, "publish", "SAFE MODE: waiting for human review before publishing")
        _notify(cfg, post,
                f"✅ SAFE MODE — everything is ready for {post['date']} (post {post['post_id']}).\n"
                f"Review:\n  - image: `{post['image']['final_path']}`\n  - video: `{post['video']['path']}`\n"
                f"  - caption: `{post['caption']['path']}`\n"
                f"Then publish with: `python src/pipeline.py publish-today --date {post['date']}`")
        return True

    vid = Path(post["video"]["path"])
    pub = publisher.make_publisher(cfg)
    try:
        me = pub.verify_token()
        logger.info(f"[{post['post_id']}] token OK (IG user {me.get('id')})")
    except Exception as e:
        post["status"] = "MANUAL_ACTION_REQUIRED"
        post["errors"].append(f"token check failed: {e}")
        _tl(post, "publish", f"token check failed: {e}", ok=False)
        _notify(cfg, post, "🛑 Instagram token check failed. Renew IG_ACCESS_TOKEN (see README → token refresh).")
        return False

    try:
        video_url = _public_video_url(cfg, post, vid)
        _tl(post, "publish", f"video hosted: {video_url}")
    except Exception as e:
        post["status"] = "MANUAL_ACTION_REQUIRED"
        post["errors"].append(f"video hosting failed: {e}")
        _tl(post, "publish", f"video hosting failed: {e}"[:200], ok=False)
        _notify(cfg, post, "🛑 Video hosting failed (MP4 needs a public HTTPS URL for Instagram). " + str(e))
        return False

    max_re = cfg["instagram"]["max_retries_publish"]
    last_err = None
    for attempt in range(max_re + 1):
        try:
            caption = post["caption"]["text"]
            media_id = pub.create_reel(video_url, caption)
            _tl(post, "publish", f"container created: {media_id}")
            pub.wait_processing(media_id, timeout=cfg["instagram"]["poll_timeout_seconds"])
            pub.publish(media_id)
            ver = pub.verify(media_id)
            post["publish"] = {
                "method": "graph_api",
                "media_id": media_id,
                "instagram_post_id": ver.get("code"),
                "permalink": ver.get("permalink"),
                "published_at": common.now_ist().isoformat(),
                "video_url": video_url,
            }
            db.setdefault("meta", {})["last_published"] = post["post_id"]
            db["meta"]["token_verified_at"] = common.now_ist().isoformat()
            post["status"] = "PUBLISHED"
            _tl(post, "publish", f"PUBLISHED {ver.get('permalink')}")
            common.append_notification(cfg, f"✅ Published {post['post_id']} → {ver.get('permalink')}")
            return True
        except Exception as e:
            last_err = str(e)
            post["retries_total"] = post.get("retries_total", 0) + 1
            post["errors"].append(f"publish attempt {attempt + 1}: {last_err}")
            _tl(post, "publish", f"attempt {attempt + 1} failed: {last_err[:200]}", ok=False)
            if attempt < max_re:
                post["status"] = "RETRYING"
                _sleep(30)
    post["status"] = "MANUAL_ACTION_REQUIRED"
    _notify(cfg, post, f"🛑 Publishing failed after {max_re + 1} attempts. Last error: {last_err}\nRetry with: `python src/pipeline.py publish-today --date {post['date']}` (assets are safe, no duplicates will occur).")
    return False


# ---------------------------------------------------------------- orchestrator
def run_pipeline(cfg, db, post, logger, until_stage: str):
    until = STAGES.index(until_stage)
    for i, stage in enumerate(STAGES):
        if i > until:
            break
        if stage == "concept":
            ok = stage_concept(cfg, db, post, logger)
        elif stage == "image":
            ok = stage_image(cfg, db, post, logger)
        elif stage == "video":
            ok = stage_video(cfg, db, post, logger)
        elif stage == "caption":
            ok = stage_caption(cfg, db, post, logger)
        elif stage == "publish":
            ok = stage_publish(cfg, db, post, logger)
        else:
            ok = True
        _save(cfg, db, post)
        if not ok:
            return 2 if post["status"] == "MANUAL_ACTION_REQUIRED" else 1
    return 0


def cmd_run(cfg, args, logger) -> int:
    common.ensure_dirs(cfg)
    date = args.date or common.today_ist()
    db = common.load_db(cfg)
    post = common.get_post_by_date(db, date)

    # STEP 1 — duplicate protection
    if post is not None:
        if post["status"] == "PUBLISHED":
            logger.info(f"ALREADY PUBLISHED for {date} ({post['post_id']}) — nothing to do")
            dashboard.render(cfg, db)
            return 0
        if post["status"] == "FAILED":
            logger.info(f"resuming previously FAILED post {post['post_id']} for {date}")
        elif post["status"] not in ("MANUAL_ACTION_REQUIRED",):
            logger.info(f"resuming post {post['post_id']} for {date} (status {post['status']})")
    else:
        post = _new_post(cfg, db, date)
        if getattr(args, "concept", None):
            post["_force_concept"] = args.concept
        db["posts"].append(post)
        _save(cfg, db, post)
        logger.info(f"created {post['post_id']} for {date}")

    until = "caption" if args.dry_run else args.stage
    rc = run_pipeline(cfg, db, post, logger, until_stage=until)
    dashboard.render(cfg, db)
    print_summary(post)
    return rc


def cmd_publish_today(cfg, args, logger) -> int:
    common.ensure_dirs(cfg)
    date = args.date or common.today_ist()
    db = common.load_db(cfg)
    post = common.get_post_by_date(db, date)
    if post is None:
        logger.error(f"no post found for {date}; run `python src/pipeline.py run` first")
        return 1
    if post["status"] == "PUBLISHED":
        logger.info("already published — no-op")
        return 0
    if post["status"] not in ("READY_TO_PUBLISH", "MANUAL_ACTION_REQUIRED", "RETRYING"):
        logger.error(f"post not ready for publish (status {post['status']})")
        return 1
    rc = stage_publish(cfg, db, post, logger, force=True)
    _save(cfg, db, post)
    dashboard.render(cfg, db)
    print_summary(post)
    return 0 if rc else 2


def print_summary(post):
    print()
    print("=" * 62)
    print(f"  {post['post_id']}  ·  {post['date']}  ·  status: {post['status']}")
    c = post.get("concept") or {}
    if c:
        print(f"  concept : {c.get('id')} | cat {c.get('category')} | formula {c.get('formula')}")
        print(f"  hook    : {c.get('hook')}")
    if post.get("image"):
        print(f"  image   : {post['image'].get('final_path')}")
    if post.get("video"):
        print(f"  video   : {post['video'].get('path')} ({post['video'].get('duration')}s)")
    if post.get("caption"):
        print(f"  caption : {post['caption'].get('path')}")
    if post.get("publish") and post.get("publish", {}).get("permalink"):
        print(f"  live    : {post['publish']['permalink']}")
    if post.get("errors"):
        print(f"  last err: {post['errors'][-1][:160]}")
    print("=" * 62)


def cmd_status(cfg, args) -> int:
    db = common.load_db(cfg)
    posts = sorted(db["posts"], key=lambda p: p["date"], reverse=True)[: args.limit]
    if not posts:
        print("no posts yet")
        return 0
    print(f"{'DATE':<12} {'POST ID':<18} {'CAT':<5} {'F':<3} {'STATUS':<24} HOOK")
    for p in posts:
        c = p.get("concept") or {}
        print(f"{p['date']:<12} {p['post_id']:<18} {str(c.get('category')):<5} {str(c.get('formula')):<3} "
              f"{p['status']:<24} {(c.get('hook') or '')[:40]}")
    return 0


def cmd_topup(cfg, args) -> int:
    import llm_topup
    logger = common.setup_logging(cfg)
    n = llm_topup.run(cfg, count=args.count, logger=logger)
    logger.info(f"topup complete: {n} new concepts added")
    return 0


def cmd_prune(cfg, args) -> int:
    logger = common.setup_logging(cfg)
    import datetime as dt
    cutoff = dt.date.today() - dt.timedelta(days=args.days)
    removed = 0
    for key in ("generated_images", "generated_videos"):
        for f in (common.ROOT / cfg["paths"][key]).iterdir():
            if f.suffix in (".jpg", ".jpeg", ".png", ".mp4") and f.stem[:8].isdigit():
                try:
                    d = dt.date(int(f.stem[0:4]), int(f.stem[4:6]), int(f.stem[6:8]))
                except Exception:
                    continue
                if d < cutoff:
                    f.unlink()
                    removed += 1
    logger.info(f"pruned {removed} files older than {args.days} days")
    return 0


def main():
    ap = argparse.ArgumentParser(description="words.for.being daily pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="run today's (or --date) pipeline")
    p_run.add_argument("--date")
    p_run.add_argument("--mode", choices=["auto", "safe"], help="override config mode")
    p_run.add_argument("--stage", choices=STAGES, default="publish", help="stop after this stage")
    p_run.add_argument("--dry-run", action="store_true", help="generate everything, skip publishing")
    p_run.add_argument("--concept", help="force a specific bank concept id (test/ops override)")
    sub.add_parser("status", help="show recent posts").set_defaults(limit=14)
    sub.add_parser("dashboard", help="render dashboard.html")
    p_pub = sub.add_parser("publish-today", help="publish a READY_TO_PUBLISH post (SAFE MODE human step)")
    p_pub.add_argument("--date")
    p_top = sub.add_parser("topup", help="generate new bank concepts with a free LLM key")
    p_top.add_argument("--count", type=int, default=None)
    p_pr = sub.add_parser("prune", help="delete generated files older than N days")
    p_pr.add_argument("--days", type=int, default=45)

    args = ap.parse_args()
    cfg = common.load_config()
    if getattr(args, "mode", None):
        cfg["instagram"]["mode"] = args.mode

    logger = common.setup_logging(cfg)
    if args.cmd == "run":
        return cmd_run(cfg, args, logger)
    if args.cmd == "publish-today":
        return cmd_publish_today(cfg, args, logger)
    if args.cmd == "status":
        return cmd_status(cfg, args)
    if args.cmd == "dashboard":
        db = common.load_db(cfg)
        dashboard.render(cfg, db)
        print(f"dashboard rendered: {common.ROOT / 'dashboard.html'}")
        return 0
    if args.cmd == "topup":
        return cmd_topup(cfg, args)
    if args.cmd == "prune":
        return cmd_prune(cfg, args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
