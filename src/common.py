"""Shared utilities: paths, config, logging, content database, notifications.

Zero paid dependencies. Stdlib + Pillow + requests only.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

# Project root = parent of src/ (override with WFB_ROOT for tests)
ROOT = Path(os.environ.get("WFB_ROOT", Path(__file__).resolve().parent.parent))

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))  # Asia/Kolkata

STATUSES = [
    "QUEUED", "GENERATING", "IMAGE_READY", "VIDEO_READY", "READY_TO_PUBLISH",
    "PUBLISHED", "FAILED", "RETRYING", "MANUAL_ACTION_REQUIRED",
]


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST)


def today_ist() -> str:
    return now_ist().date().isoformat()


def load_config() -> dict:
    p = ROOT / "config" / "config.json"
    if not p.exists():
        raise SystemExit(f"config not found: {p}")
    cfg = json.loads(p.read_text())
    env_mode = os.environ.get("WFB_MODE")
    if env_mode:
        cfg["instagram"]["mode"] = env_mode
    return cfg


def db_path(cfg: dict) -> Path:
    return ROOT / cfg["paths"]["database"] / "content.json"


def load_db(cfg: dict) -> dict:
    p = db_path(cfg)
    if not p.exists():
        return {"posts": [], "meta": {"created": now_ist().isoformat()}}
    return json.loads(p.read_text())


def save_db(cfg: dict, db: dict) -> None:
    p = db_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False))
    tmp.replace(p)
    write_history_index(cfg, db)


def write_history_index(cfg: dict, db: dict) -> None:
    """Lightweight index for fast originality checks + dashboard."""
    idx = {
        "updated": now_ist().isoformat(),
        "count": len(db["posts"]),
        "posts": [
            {
                "post_id": p["post_id"],
                "date": p["date"],
                "status": p["status"],
                "category": (p.get("concept") or {}).get("category"),
                "formula": (p.get("concept") or {}).get("formula"),
                "hook": (p.get("concept") or {}).get("hook", "")[:90],
            }
            for p in db["posts"]
        ],
    }
    out = ROOT / cfg["paths"]["database"] / "history.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(idx, indent=2, ensure_ascii=False))


def get_post(db: dict, post_id: str) -> dict | None:
    return next((p for p in db["posts"] if p["post_id"] == post_id), None)


def get_post_by_date(db: dict, date: str) -> dict | None:
    return next((p for p in db["posts"] if p["date"] == date), None)


def make_post_id(date: str, seq: int = 1) -> str:
    return f"wfB-{date.replace('-', '')}-{seq:03d}"


def setup_logging(cfg: dict, name: str = "wfb") -> logging.Logger:
    logdir = ROOT / cfg["paths"]["logs"]
    logdir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(logdir / "pipeline.log")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def append_notification(cfg: dict, text: str) -> None:
    p = ROOT / cfg["notifications"]["file"]
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"\n## {now_ist().isoformat()}\n{text.strip()}\n")


def ensure_dirs(cfg: dict) -> None:
    for key in ("generated_images", "generated_videos", "captions", "logs", "database"):
        (ROOT / cfg["paths"][key]).mkdir(parents=True, exist_ok=True)
    (ROOT / "database" / "bank").mkdir(parents=True, exist_ok=True)
    (ROOT / "fonts").mkdir(exist_ok=True)
    (ROOT / "creative").mkdir(exist_ok=True)
