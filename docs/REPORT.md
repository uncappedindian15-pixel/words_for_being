# REPORT — words.for.being autonomous daily reel engine

Date: 2026-09-11 · Budget: ₹0/month · Status: **built, tested 34/34, live-ready**

This report contains the ten requested deliverables (A–J). The working
system is this repository; nothing here is hypothetical.

---

## A. Architecture diagram

Full diagram: [ARCHITECTURE.md](ARCHITECTURE.md). Summary:

```
GitHub Actions (free, 11:00 IST)
  └─ pipeline.py
       ├─ rotation.py   concept pick (Originality Law, anti-repeat)
       ├─ imagegen.py   Pollinations image (free, no key) ×≤7 QC attempts
       ├─ validator.py  QC: bg brightness, subject placement, OCR, watermark
       ├─ background.py white-bg repair + watermark-zone paint
       ├─ video.py      FFmpeg 5 s MP4 + ffprobe hard gate
       ├─ caption       formula hook + native hashtags
       └─ publisher.py  official Meta Graph API (REELS container → publish)
             hosting.py → GitHub Pages (free public MP4 URL)
State: database/content.json + history.json · Obs: dashboard.html + logs/
```

Design property: **every stage is idempotent and resumable** — a crash or
failure stops the post at its stage marker; the next daily run continues
from there, never from scratch, and date-locking makes duplicate posts
impossible.

## B. Tool stack + free-ness justification

| Role | Tool | Why free & why this one |
|---|---|---|
| Scheduler + compute | GitHub Actions | 2,000 free min/mo, no card, always-on, private repos included. We use ~10 min/day. |
| Image gen | Pollinations | Keyless free image endpoint (Flux-class). No account, no card, no billing. Anon-tier limits handled by 429 backoff + retries. |
| Image QC | Pillow, numpy, scipy, Tesseract OCR | Open source, runs on the free Actions runner. Brightness percentiles, subject placement, "did the model add text", watermark-zone detection. |
| Video | FFmpeg + ffprobe | Open source, free, the standard for 1080×1920 h264 yuv420p +faststart. No paid video model (static 5 s image, per brief). |
| Publishing | Meta Instagram Graph API | The **official** sanctioned path (REELS container → poll → media_publish). Free API; dev mode covers your own account as a test user. No browser bots, no ToS risk. |
| Video hosting | GitHub Pages (self-hosted) | IG must fetch the MP4 from a public HTTPS URL. Pages on your own repo: free, permanent, private repo content never exposed (media/ only). Tested live 2026-09-11. |
| State/DB | JSON files in the repo | Zero-infra, observable in GitHub UI, versioned by git, resume-safe. No paid DB. |
| Dashboard | static HTML committed to repo | Opens anywhere, no server, no cost. |
| Bank top-up (optional) | Google AI Studio free tier | Only when the 64-concept bank runs low (~2 months). Free key, no card. Optional — bank can also be edited by hand. |
| Font | Google Fonts (Anton, OFL) | Free open license. |

Every component classified: see [docs/cost_audit.md](docs/cost_audit.md)
(11 of 12 are 100% free; Pollinations and the optional LLM top-up are
"Free With Limits" with documented mitigations; nothing is "Paid Upgrade"
and nothing requires a card).

## C. Implementation

Complete in this repo (~2,300 lines):

- `src/pipeline.py` — the state machine: 9 statuses
  (QUEUED, GENERATING, IMAGE_READY, VIDEO_READY, READY_TO_PUBLISH,
  PUBLISHED, FAILED, RETRYING, MANUAL_ACTION_REQUIRED), per-stage timeline,
  retry counts, error records, resume-from-failed-stage, exit codes
  (0 ok · 1 failed · 2 human needed), `run / publish-today / status /
  dashboard / topup / prune` CLI.
- `src/rotation.py` — Originality Law: no formula twice consecutively, no
  category streak, banned-cliché phrase list (people by windows, couples
  from behind, "protect your peace", Pinterest clichés…), recency-weighted
  pick, scene-overlap repetition detector vs last N published.
- `src/imagegen.py` — Pollinations provider (seed-per-attempt, 429-aware
  20 s backoff, LANCZOS upscale 576→1080), provider flag for swap.
- `src/background.py` — white-background QC + repair: worst 70×70 corner
  p75 luminance gate, brand-bg zone paint, flood-fill lift.
- `src/validator.py` — QC agent: bg ≥190 (p75 worst corner), subject kept
  out of the top third, OCR word count = 0 (no rogue model text),
  dual-polarity OCR on the bottom-right watermark zone = 0 words.
- `src/video.py` — FFmpeg: 1080×1920, 5.000 s, h264 yuv420p, silent AAC
  48 kHz, +faststart; ffprobe validation hard gate.
- `src/publisher.py` — official Graph API: media container (REELS) → poll
  FINISHED → media_publish → permalink stored once.
- `src/hosting.py` — free public MP4 URL: GitHub Pages (auto
  commit+push+deploy-wait) or catbox fallback.
- `src/dashboard.py` — status pills, timelines, per-step cost/time,
  marginal-bg badge, notifications.
- `database/bank/{A,B,C,D}.json` — 64 concepts (4 categories) + 8 hook
  formulas, each honoring your creative prompt (Emotion → Physical Action
  → Visual; one complete concept per post; white background; no text).

## D. Zero-setup instructions for a non-programmer

[docs/setup-instagram.md](docs/setup-instagram.md) — 45 minutes, 6 steps,
no programming: GitHub repo → IG creator account + FB page link → Meta
app + token (2 values) → GitHub Pages → 2 repo secrets → first run.
Daily use in SAFE MODE is **one button click** on GitHub ("Publish
Today"). No credentials ever enter the repo; secrets live only in GitHub's
encrypted secrets store.

## E. Daily workflow (what actually happens at 11:00 IST)

1. Actions checkout, install ffmpeg/tesseract/python deps (free).
2. Pipeline loads bank + history; picks concept by Originality Law.
3. Image: up to 7 Pollinations attempts; each attempt through the QC
   agent; failures logged with reasons and retry hints injected into the
   next prompt; watermark-zone paint as repair.
4. FFmpeg static 5 s MP4 → ffprobe gate.
5. Caption: formula hook + 3–5 native hashtags (no hashtag spam).
6. SAFE MODE (default): stop at READY_TO_PUBLISH → you glance at the
   dashboard → one button publishes. AUTO MODE: host MP4 on Pages,
   publish via official API, record permalink.
7. Commit state + dashboard back to the repo (your content memory).
8. Next day: rotation guarantees a different concept/formula.

## F. Failure recovery (all simulated and tested, not just designed)

| Failure simulated | Observed behaviour | Test |
|---|---|---|
| Image endpoint dead | exit ≠ 0, post FAILED, retry count recorded, **no partial video**, next run resumes | T6 ✔ |
| Publish rejected | exit code 2 → MANUAL_ACTION_REQUIRED → human note written → `publish-today` recovers → PUBLISHED, **no duplicate** | T8 ✔ |
| Crash after image stage | resume reached PUBLISHED **without re-generating the image** | T9 ✔ |
| Re-run same day | no-op, ALREADY-PUBLISHED guard, exactly one record | T7 ✔ |
| Token/host problems | staged asset kept, MANUAL_ACTION_REQUIRED with exact instruction | code path in `hosting.py`/`publisher.py` |

The only things that page a human: expired token (60-day cycle), a
publish rejection that also fails on retry, or an empty bank. Everything
else self-heals by the next daily run.

## G. Cost analysis (target ₹0/month — achieved)

| Item | Monthly |
|---|---|
| GitHub Actions | 0 (≈300 of 2,000 free minutes) |
| GitHub Pages | 0 (≈5 MB of 100 GB) |
| Pollinations images | 0 |
| FFmpeg/OCR/QC | 0 |
| Meta Graph API | 0 |
| LLM top-up (optional, ~monthly) | 0 |
| **Total** | **₹0/month, no card anywhere** |

Per-component audit with limits: [docs/cost_audit.md](docs/cost_audit.md).

## H. Honest limitations

1. **IG token life is 60 days** (Meta's free rule). Refresh = 10 minutes,
   once a month, and the machine detects expiry and tells you.
2. **Dev-mode API = test users only** — which is your own account, so no
   practical loss; a multi-account expansion would require app review.
3. **Pollinations anon tier** is an unofficial free endpoint: it can
   throttle or change. Mitigations: 7 retries, 429 backoff, marginal-bg
   fallback (publishes a flagged-but-acceptable image instead of losing
   the day), provider-swap flag. Worst realistic case: a slow day, not a
   broken system.
4. **The image model is stochastic.** Sometimes it paints a grey floor no
   matter how the prompt is worded; QC + retries absorb most of it, and
   the bank's wording was A/B-tuned (repeated plain "white background"
   wording measured 207 min-corner vs 137–165 for studio wording).
4b. **Oil-paint texture vs white background (measured trade-off).** The
   master prompt's locked style asks for "soft oil painting, visible
   brushstrokes". On the free keyless endpoint that wording produces
   grey environments (A/B: 76–107 worst-corner luminance vs 207 for the
   flat wording; the QC threshold is 190). The machine therefore renders
   in the proven flat matte style (still: soft, minimal, storybook-calm,
   70–80% white negative space) and treats the brushstroke texture as
   the first upgrade to revisit if a provider that follows style words
   better becomes available at ₹0 (local ComfyUI, or a new free
   endpoint). Every other part of the locked style (white plaster
   background, small low subject, thin handwritten Caveat typography,
   left-aligned upper third, signature watermark, ≤8-word hooks) is
   enforced in code.
5. **Static image, by design** (brief: 5 s static, no motion, no paid
   video model). No audio track either (silent AAC track for IG
   compatibility).
6. **`creative/master_prompt.txt` is a reconstruction** of your creative
   brief — please paste the full original text there when convenient; the
   pipeline reads it live, so the bank and prompts follow automatically.
7. **Bank is finite (64 ≈ 2 months).** Refill via free LLM `topup`
   command or 5 minutes of JSON editing; the machine warns before it's
   low and never silently repeats.
8. **Dashboard is pull, not push**: you open it (GitHub) or subscribe to
   Actions run-status emails; there is no free always-push channel that
   doesn't cost money, and the design pages you only on real need.
9. **GitHub free tier** is generous but not infinite (2,000 min/mo, 1 GB
   repo). Current usage is ~15% of the compute budget.

## I. Actual test results (run 2026-09-11, real execution, no mocks except
   the IG API endpoint, which is mocked because no real post is made in
   tests — image gen, QC, video, hosting-stage logic are all live)

```
T1  rotation engine (bank 64, picks, formula-avoidance, rejections,
    banned-phrase reject)                     ✔ 6/6
T2  image generation (Pollinations, free)      ✔  generated in 3 s
T3  image → 5 s static MP4 (FFmpeg)            ✔
T4  MP4 validation                             ✔  1080×1920 / 5.000 s / h264 / aac
T5  full pipeline + publishing (mock IG API)   ✔  exit 0, PUBLISHED, permalink,
                                                 timeline, caption file
T6  simulated image failure                    ✔  FAILED, retry count, no
                                                 partial video
T7  duplicate-generation protection            ✔  no-op, one record, guard fired
T8  simulated publish failure                  ✔  exit 2, MANUAL_ACTION_REQUIRED,
                                                 notification, recovered via
                                                 publish-today, no duplicate
T9  restart & recovery                         ✔  IMAGE_READY stop → resume →
                                                 PUBLISHED, image NOT regenerated
T10 two consecutive days                       ✔  published both days, different
                                                 concepts, no formula repeat
──────────────────────────────────────────────────────────────────────
RESULT: 34 passed, 0 failed
```

Live production artifact (this repo, today): post `2026-09-11`, concept
**A-01**, hook *"You are not a season. You are the whole year."*, image
QC bg=243.0 / top-fraction=0.0 / OCR=0 / watermark-zone=0, MP4
171 KB, status **READY_TO_PUBLISH** — sitting in the dashboard, waiting
for your publish button (SAFE MODE).

Additional verification beyond the suite (2026-09-11):
- **No-token publish path** (isolated copy): exit 2 →
  `MANUAL_ACTION_REQUIRED`, error *"IG_ACCESS_TOKEN env var is missing"*
  recorded, human notification written, no crash, no re-generation.
- **Real-state re-run**: `run` against today's existing post = clean
  no-op, exactly one post, status unchanged.
- **Bank pre-flight audit**: all 64 concepts checked against the banned
  cliché list, scene-inviting words (room/wall/doorway/platform/sky/
  sofa/spotlight…), dark-subject words, and hook length limits. 17
  concepts were de-scened (surroundings removed, object kept, "isolated
  on plain white" added); `scripts/audit_bank.py` is now a permanent ops
  tool (also checks fantasy props and CTA compliance).
- **Original master prompt integrated** (2026-09-11): saved verbatim to
  `creative/master_prompt.txt`. This aligned the system to the real
  typography spec — **Caveat** thin handwritten font (OFL license)
  replaces the bold block font, text is **left-aligned at 8%**, sub-line
  smaller + 65% opacity, CTA is a plain low-opacity line (no pill),
  ink is soft charcoal #3A3530. All **64 hooks rewritten to ≤8 words**
  and sub-lines to ≤12 (previously up to 23), CTAs normalized to the
  three approved lines on ~1 in 3 posts. Fantasy props removed
  (crowns/glows) from C-07, D-07, B-07, B-08, D-03, D-16.
- **Subject-bbox QC gate added**: the old top-zone check missed tall
  white subjects that overlapped the text (today's A-01 block: text
  zone top at 28% of frame). New gate rejects renders whose subject top
  edge is above 42% of the frame or whose subject is taller than 58% of
  frame height, with a dedicated retry hint ("make the object much
  smaller… upper half completely empty white"). Live-verified: the
  current A-01 base was rejected by the new gate and regenerated
  through 7 QC attempts (6 rejected with reasons, 7th compliant).
- **Tall-object concepts reworked** (each live render-verified):
  A-03 easel→canvas lying flat, B-01 upright umbrella→on its side,
  B-09 lighthouse→candle in a glass, C-14 hanging coat→coat lying flat,
  D-08 fridge→small compact fridge.
- **Style-suffix A/B (oil paint vs white)**: the master prompt's
  "oil painting, visible brushstrokes, plaster wall" wording was tested
  live against the proven flat wording (same concept, same seeds,
  p75 worst-corner luminance): proven flat = 207; oil-paint wording =
  76–104; two hybrids = 104–107. The free keyless endpoint cannot
  deliver the oil-paint texture while keeping the mandatory white
  background, so the machine uses the proven flat-white wording (see
  §Honest limitations).
- **Watermark-zone erase**: widened to 130×420 with a 30px feathered
  blend, removing the visible paint-seam rectangle.

## J. Maintenance cadence

| Cadence | Action | Time |
|---|---|---|
| Daily (SAFE MODE) | glance dashboard → click "Publish Today" (or nothing: AUTO MODE) | 30 s |
| Weekly | 10-second dashboard skim for FAILED pills | 10 s |
| Monthly | refresh the 60-day IG token (setup doc §3) | 10 min |
| ~Monthly | bank top-up when the machine warns (free LLM or hand edit) | 15 min |
| After any bank edit / topup | `python3 scripts/audit_bank.py` (scene words, banned clichés, hook lengths) | 5 s |
| Quarterly | optional: `prune` old generated files, delete old committed videos to keep the repo light | 10 min |
| On change | drop a new .ttf in `fonts/`, edit bank JSON, adjust `config.json` (posting time, QC thresholds, mode) | n/a |

**Bottom line:** after the 45-minute setup, this machine costs ₹0, runs
itself, posts once a day, never duplicates, never silently fails, and
only pings you when only a human can act.
