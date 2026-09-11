#!/usr/bin/env python3
"""Bank pre-flight audit.

Checks every concept in database/bank/ for:
  1. banned cliché phrases (from rotation.BANNED_PHRASES)
  2. scene-inviting words (room/wall/doorway/platform/sky/sofa/spotlight…)
     — these make the free image model render a grey environment, which the
     white-background QC then rejects. Fix by de-scening: keep the OBJECT,
     drop the SURROUNDINGS, add "isolated on plain white".
  3. dark subject words (black/charcoal/navy/…) — usually fine when the
     object itself is small on white, flagged for review.
  4. hook length limits (must match config: hook_max_words / hook_max_chars).

Usage:  python3 scripts/audit_bank.py
Exit:   0 = clean, 1 = issues found.
Run this after any manual bank edits or after `topup`.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import common  # noqa: E402
import rotation  # noqa: E402

cfg = common.load_config()
Q = cfg.get("quality", cfg.get("qc", {}))
MAX_WORDS = Q.get("hook_max_words", 8)
MAX_CHARS = Q.get("hook_max_chars", 64)
SUB_WORDS = Q.get("subline_max_words", 12)

SCENE = [
    "room", "wall clock", "wall calendar", "wall hook", "on the wall",
    "doorway", "kitchen", "bathroom", "bedroom", "hallway",
    "street", "outdoor", "platform", " sky", "sofa", "armchair",
    "on a bed", "in the middle of", "spotlight", "shadow long",
]
DARK = ["black", "charcoal", "navy", "midnight", "grey storm", "gray storm"]
FANTASY = ["crown", "glow", "jewel", "magic", "mystic", "treasure", "ornate",
           "gold", "sparkle", "halo", "aurora"]
APPROVED_CTAS = {"", "Tag someone who needs this.", "Save this for later.",
                 "Which line hit you the most?"}

issues = 0
total = 0
for cat in "ABCD":
    bank = json.loads((ROOT / "database" / "bank" / f"{cat}.json").read_text())
    items = bank["concepts"] if isinstance(bank, dict) else bank
    for c in items:
        total += 1
        prompt = c.get("image_prompt", "")
        low = prompt.lower()
        cid = c["id"]
        for b in getattr(rotation, "BANNED_PHRASES", []):
            if b.lower() in low:
                print(f"{cid}: BANNED phrase '{b}'")
                issues += 1
        for w in SCENE:
            if w in low:
                print(f"{cid}: scene word '{w.strip()}'  ->  {prompt[:80]}")
                issues += 1
        for d in DARK:
            if d in low:
                print(f"{cid}: dark word '{d}' (review)  ->  {prompt[:80]}")
                issues += 1
        for f_ in FANTASY:
            if f_ in low:
                print(f"{cid}: fantasy prop '{f_}'  ->  {prompt[:80]}")
                issues += 1
        hook = c.get("hook", "")
        hw = len(hook.split())
        if hw > MAX_WORDS:
            print(f"{cid}: hook {hw} words > {MAX_WORDS}")
            issues += 1
        if len(hook) > MAX_CHARS:
            print(f"{cid}: hook {len(hook)} chars > {MAX_CHARS}")
            issues += 1
        sub = c.get("subline") or ""
        sw = len(sub.split())
        if sw > SUB_WORDS:
            print(f"{cid}: subline {sw} words > {SUB_WORDS}")
            issues += 1
        cta = c.get("cta") or ""
        if cta not in APPROVED_CTAS:
            print(f"{cid}: CTA not from approved set: {cta!r}")
            issues += 1

print(f"\naudited {total} concepts: {'CLEAN' if issues == 0 else f'{issues} issue(s)'}")
sys.exit(1 if issues else 0)
