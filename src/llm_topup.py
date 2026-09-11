"""Optional zero-cost LLM top-up for the concept bank.

The core pipeline runs entirely on the pre-authored bank (₹0, no keys).
This module *optionally* refreshes the bank with fresh concepts when it
runs low, using a genuinely free LLM API key (no credit card needed):

  provider "gemini"     -> env GEMINI_API_KEY   (Google AI Studio free tier)
  provider "groq"       -> env GROQ_API_KEY     (Groq free tier)
  provider "openrouter" -> env OPENROUTER_API_KEY (free models)

If no key is set: this module does nothing and the system keeps working
from the bank (cycling with full originality checks after exhaustion).

The creative constitution (creative/master_prompt.txt) is injected
verbatim — it is the single source of creative truth.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

import requests

import common
import rotation

SCHEMA_HINT = """
Return ONLY a JSON array with exactly {count} objects, each exactly this shape:
[
  {
    "category": "A" | "B" | "C" | "D",
    "formula": 1-8,
    "emotional_core": "one specific emotion",
    "visual_concept": "the scene in one sentence",
    "physical_action": "the object mid-action",
    "hook": "the line (max ~16 words)",
    "subline": "optional max 12 words or empty string",
    "cta": "optional short CTA or empty string",
    "caption": "2-4 short lines in native IG voice",
    "hashtags": ["#wordsforbeing", "...4-5 niche tags..."],
    "image_prompt": "scene only, object-led, mid-action, no text, no people, no faces, no hands"
  }
]
No markdown, no commentary, JSON only.
Every concept must pass the Originality Law: it must be clearly different from
the recent concepts listed below, and must not reuse any of their physical
actions. Categories must be spread (roughly one of each per 4).
"""

RECENT_BLOCK = "Recent concepts (do NOT repeat these):"


def _master_prompt() -> str:
    p = common.ROOT / "creative" / "master_prompt.txt"
    return p.read_text() if p.exists() else "(master prompt missing)"


def _recent_concepts(bank: list, n: int = 12) -> list:
    tail = list(reversed(bank))[:n]
    return [
        f"- {c['id']} [{c.get('category')}/F{c.get('formula')}] action: {c.get('physical_action')} | hook: {c.get('hook')}"
        for c in tail
    ]


def _build_prompt(cfg, count: int, bank: list) -> str:
    return (
        _master_prompt()
        + "\n\n" + SCHEMA_HINT.replace("{count}", str(count))
        + "\n" + RECENT_BLOCK + "\n" + "\n".join(_recent_concepts(bank))
    )


def _call_llm(cfg, prompt: str) -> str:
    provider = cfg["bank"].get("llm_provider", "gemini")
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        model = cfg["bank"].get("gemini_model", "gemini-2.5-flash")
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.95, "responseMimeType": "application/json"},
            },
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    if provider == "groq":
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY not set")
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": cfg["bank"].get("groq_model", "llama-3.3-70b-versatile"),
                  "messages": [{"role": "user", "content": prompt}], "temperature": 0.95},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": cfg["bank"].get("openrouter_model"),
                  "messages": [{"role": "user", "content": prompt}], "temperature": 0.95},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError(f"unknown llm provider {provider}")


def _extract_json(text: str):
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON array in LLM response")
    return json.loads(m.group(0))


def _next_id(bank: list, category: str) -> str:
    nums = [int(c["id"].split("-")[1]) for c in bank if c.get("category") == category and re.match(r"^[A-D]-\d+$", c.get("id", ""))]
    return f"{category}-{(max(nums) if nums else 0) + 1:02d}"


def run(cfg, count: int | None = None, logger=None) -> int:
    logger = logger or common.setup_logging(cfg, name="wfb-topup")
    provider = cfg["bank"].get("llm_provider", "gemini")
    key_env = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[provider]
    if not os.environ.get(key_env):
        logger.info(f"topup skipped: {key_env} not set (bank-only mode continues)")
        return 0

    bank = rotation.load_bank(cfg)
    count = count or cfg["bank"].get("topup_count", 12)
    logger.info(f"topup: requesting {count} concepts via {provider}")
    try:
        raw = _call_llm(cfg, _build_prompt(cfg, count, bank))
        items = _extract_json(raw)
    except Exception as e:
        logger.error(f"topup LLM call failed: {e}")
        return 0

    existing = {c.get("physical_action", "").strip().lower() for c in bank}
    kept = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("category") not in rotation.CATEGORIES:
            continue
        if it.get("formula") not in rotation.FORMULAS:
            continue
        for field in ("emotional_core", "visual_concept", "physical_action", "hook", "image_prompt", "caption"):
            if not str(it.get(field) or "").strip():
                break
        else:
            action = str(it.get("physical_action", "")).strip().lower()
            if action in existing:
                continue
            if any(rotation.jaccard(
                it.get("emotional_core", "") + " " + action,
                c.get("emotional_core", "") + " " + c.get("physical_action", "")
            ) >= 0.5 for c in bank[-30:]):
                continue
            it["id"] = _next_id(bank + kept, it["category"])
            it["subline"] = it.get("subline") or ""
            it["cta"] = it.get("cta") or ""
            it["hashtags"] = (it.get("hashtags") or ["#wordsforbeing"])[:6]
            kept.append(it)

    if not kept:
        logger.warning("topup: all generated concepts were rejected by dedupe")
        return 0
    stamp = dt.date.today().isoformat().replace("-", "")
    out = common.ROOT / cfg["paths"]["database"] / "bank" / f"topup_{stamp}.json"
    out.write_text(json.dumps({"category": "mixed", "category_name": "LLM top-up", "concepts": kept},
                              indent=2, ensure_ascii=False))
    logger.info(f"topup: added {len(kept)} concepts -> {out.name}")
    return len(kept)


def maybe_topup(cfg, bank: list, logger) -> None:
    """Called by the pipeline: top up only when the bank is running low."""
    used_ids = set()
    try:
        db = common.load_db(cfg)
        used_ids = {p.get("concept", {}).get("id") for p in db["posts"]}
    except Exception:
        pass
    unused = len(bank) - len(used_ids)
    if unused >= cfg["bank"].get("threshold_topup", 10):
        return
    logger.info(f"bank low (unused={unused}) — attempting topup")
    run(cfg, logger=logger)
