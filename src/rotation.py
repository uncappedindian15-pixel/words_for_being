"""Rotation engine + originality checks.

Enforces the creative constitution:
  - no repeat of a used concept id
  - no repeat of the previous post's text formula
  - no category streak longer than allowed
  - no physical action reused within N days
  - semantic similarity to recent posts stays below threshold
  - zero banned (cliche) phrases
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import common

CATEGORIES = {
    "A": "Self / Growth",
    "B": "Romantic / Loving",
    "C": "Confrontational / Relationship Truths",
    "D": "Playful / Witty",
}
FORMULAS = {
    1: "Blunt ultimatum",
    2: "Hot take/opinion",
    3: "Casual raw confession",
    4: "Internet-native meme phrasing",
    5: "One-line metaphor",
    6: "Life tip / Rule",
    7: "Micro-story",
    8: "Direct address",
}

# From creative/master_prompt.txt section 5 (hard anti-cheat list)
BANNED_PHRASES = [
    "protect your peace", "peace of mind", "trust the process",
    "good things take time", "it is what it is", "sitting by a window",
    "sits by the window", "walking from behind", "couple walking away",
    "back of a couple", "love yourself first", "self-love quote",
    "abundance mindset", "dream big", "work hard play hard", "girl boss",
    "manifest", "vibes only", "you are enough",
]


def tokenize(s: str) -> set:
    return set(re.findall(r"[a-z0-9']+", (s or "").lower()))


def jaccard(a: str, b: str) -> float:
    A, B = tokenize(a), tokenize(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def banned_hits(text: str) -> list:
    low = (text or "").lower()
    return [b for b in BANNED_PHRASES if b in low]


def load_bank(cfg: dict) -> list:
    bankdir = common.ROOT / cfg["paths"]["database"] / "bank"
    bank = []
    for f in sorted(bankdir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            raise SystemExit(f"bank file {f.name} is not valid JSON: {e}")
        file_category = data.get("category")
        for c in data.get("concepts", []):
            c.setdefault("category", file_category)
            c["_source"] = f.stem
            bank.append(c)
    return bank


def _concept_of(post: dict) -> dict:
    return post.get("concept") or {}


def pick_concept(cfg: dict, bank: list, history: list, today: str | None = None):
    """Select today's concept from the bank.

    history: list of post records sorted by date ASC (all statuses).
    Returns (concept_or_None, report).
    """
    report = {
        "chosen": None, "score": None, "cycle_reset": False,
        "rejections": [], "candidates": len(bank), "errors": [],
    }
    today = today or common.today_ist()
    th = cfg["quality"]["similarity_threshold"]
    lookback = cfg["quality"]["recent_lookback"]
    action_days = cfg["quality"]["action_reuse_days"]
    no_streak = cfg["rotation"]["no_category_streak"]

    used_ids = {_concept_of(p).get("id") for p in history}
    last = history[-1] if history else None
    last_formula = _concept_of(last).get("formula") if last else None
    last_cat = _concept_of(last).get("category") if last else None

    cat_counts: dict[str, int] = {}
    for p in history:
        c = _concept_of(p).get("category")
        if c:
            cat_counts[c] = cat_counts.get(c, 0) + 1

    streak = 0
    for p in reversed(history):
        c = _concept_of(p).get("category")
        if c and c == last_cat:
            streak += 1
        else:
            break

    fresh = [c for c in bank if c["id"] not in used_ids]
    if not fresh:
        report["cycle_reset"] = True
        fresh = bank  # bank exhausted: reuse only with strict checks (Originality Law still applies)

    for c in fresh:
        reasons: list[str] = []

        if not report["cycle_reset"] and cfg["rotation"]["no_formula_repeat"]:
            if c.get("formula") == last_formula:
                reasons.append(f"formula {c.get('formula')} repeats last post")

        if streak >= no_streak and c.get("category") == last_cat:
            reasons.append(f"category streak {last_cat} x{streak}")

        for p in history[-lookback:]:
            pc = _concept_of(p)
            sim = jaccard(
                c.get("emotional_core", "") + " " + c.get("physical_action", ""),
                pc.get("emotional_core", "") + " " + pc.get("physical_action", ""),
            )
            if sim >= th:
                reasons.append(f"similar to {pc.get('id')} (sim={sim:.2f})")
                break

        for p in history:
            act = _concept_of(p).get("physical_action", "")
            if act and act.strip().lower() == (c.get("physical_action") or "").strip().lower():
                try:
                    days = (dt.date.fromisoformat(today) - dt.date.fromisoformat(p["date"])).days
                except Exception:
                    days = 9999
                if 0 <= days < action_days:
                    reasons.append(f"action reused {days}d ago")
                    break

        hits = banned_hits(c.get("hook", "") + " " + c.get("subline", "") + " " + c.get("emotional_core", ""))
        if hits:
            reasons.append(f"banned phrase: {hits}")

        if reasons:
            report["rejections"].append({"id": c["id"], "reasons": reasons})
            continue

        # score: prefer least-used category, then deterministic spread
        score = -cat_counts.get(c.get("category"), 0) * 10
        if c.get("category") == last_cat:
            score -= 2
        report.setdefault("scores", []).append((score, c["id"]))
        if report["chosen"] is None or score > report["score"]:
            report["chosen"] = c
            report["score"] = score

    if report["chosen"] is None:
        report["errors"].append("no concept passed originality checks")
    return report["chosen"], report
