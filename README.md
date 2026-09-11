# words.for.being — Zero-Cost Daily Reel Engine

A fully autonomous machine that, every day:

1. picks a fresh creative concept (no repeats, no formula streaks),
2. generates one 1080×1920 image (free AI, no API key),
3. runs a QC agent (background brightness, subject placement, no rogue text,
   no provider watermark),
4. renders a 5-second silent MP4 with FFmpeg (open source),
5. writes a native-feeling caption + hashtag set,
6. publishes to Instagram via the **official Meta Graph API**,
7. logs everything, records the permalink, and moves to the next idea.

**Total cost: ₹0/month.** No paid APIs, no VPS, no bots, no card-required
services. See [docs/cost_audit.md](docs/cost_audit.md).

**Status: built, tested, and debugged.** Full test suite: **34/34 passing**
(2026-09-11) — see [docs/REPORT.md](docs/REPORT.md) for the complete
deliverable set (architecture, stack, tests, failures, limitations).

---

## How the day works

Runs automatically at **11:00 IST** (05:30 UTC) on GitHub Actions (free tier):

```
05:30 UTC  GitHub Actions starts (free runner)
           ├─ load bank + history (64 concepts, 4 categories)
           ├─ pick concept: Originality Law (no repeat formula, no category
           │   streak, no banned cliché phrases, recency-weighted)
           ├─ image: Pollinations (free, no key) → 7 QC-gated attempts
           │   (background p75 corner ≥ 190, subject out of top third,
           │   OCR text = 0, watermark zone = 0) + watermark-zone paint
           ├─ ffmpeg: 1080×1920, 5.000 s, h264 yuv420p, silent AAC,
           │   +faststart
           ├─ ffprobe validation (hard gate)
           ├─ caption + hashtags (formula-driven, 3–5 tags, native tone)
           └─ publish:
                SAFE MODE (default) → status READY_TO_PUBLISH, stop.
                                       You click "Publish Today" in
                                       GitHub Actions → PUBLISHED.
                AUTO MODE  → host video on GitHub Pages,
                             create IG container → poll → media_publish
                             → permalink logged → PUBLISHED
```

If any step fails: the post is marked `FAILED` (never silent), the error is
recorded with a retry count, and the **next day's run resumes the same post
from the failed stage** — it does not restart from scratch, and it can never
produce a duplicate post (date+ID locking; PUBLISHED is immutable).

## One-time setup (≈45 minutes, no programming)

Full step-by-step: [docs/setup-instagram.md](docs/setup-instagram.md).

1. **GitHub account** (free) + create a repo, upload this folder.
2. **Instagram professional account** (switch your @words.for.being to
   Creator) + a free Facebook Page linked to it.
3. **Meta developer app** (free, no card): create a Business app, add the
   Instagram product, add yourself as a test user, generate a
   long-lived token. You get 2 values: `IG_ACCESS_TOKEN`, `IG_USER_ID`.
4. **GitHub Pages** (free): enable Pages on the repo, copy the URL into
   `config/config.json` → `video_public_host.base_url`.
5. **Repository secrets**: `IG_ACCESS_TOKEN`, `IG_USER_ID`.
6. **First run**: Actions → "Daily Reel" → Run workflow. Check
   `dashboard.html` in the repo.

## Daily operation

**SAFE MODE (default — recommended):**
- 11:00 IST — the machine has already built the post and is waiting.
- Open the repo → `dashboard.html` (or the GitHub Actions run log).
- If you like it: Actions → **"Publish Today"** → click **Run workflow**
  → done. One button.
- If you don't: don't click. The post stays `READY_TO_PUBLISH`; tomorrow's
  run publishes the *new* day's concept (today's is archived as skipped —
  no duplicates, no spam).

**AUTO MODE** (zero human touches after setup):
- Set `"mode": "AUTO"` in `config/config.json` and commit.
- From then on the machine publishes by itself every day at 11:00 IST.

## When the machine needs you (rare)

It only interrupts you for things a person must do:

| Situation | What you do | Takes |
|---|---|---|
| `MANUAL_ACTION_REQUIRED` (e.g. token expired, Pages deploy stuck) | follow the note in `logs/notifications.md`, then Actions → "Publish Today" | 2–10 min |
| IG token expires (every 60 days) | regenerate long-lived token in Meta, paste into repo secret | 10 min, once a month |
| Bank nearly empty | run `python src/pipeline.py topup` with a free Gemini API key (optional; bank of 64 = ~2 months) or add JSON by hand | 15 min, ~monthly |

## The creative system (your prompt, enforced in code)

- **Emotion → Physical Action → Visual** — the master prompt in
  `creative/master_prompt.txt` is embedded in every generated concept.
- **64 concepts** in `database/bank/{A,B,C,D}.json` (4 categories), each a
  single complete visual: one object, white background, small subject low in
  frame, no text.
- **Originality Law** (`src/rotation.py`): never the same formula twice in a
  row, no category streak, banned-cliché phrase list checked against every
  concept and every image attempt, recency-weighted selection, and a
  repetition detector that compares each candidate to the last N published
  concepts (same scene words / same formula / same palette = reject).
- **8 hook formulas** in the bank; hooks are length-checked (≤24 words,
  ≤140 chars) before anything renders.
- The bank is finite by design: when it runs low the machine tells you (it
  does not quietly start repeating).

## Files

```
config/config.json        handle, mode, time, retries, QC thresholds, hosts
creative/master_prompt.txt  your creative prompt (original, verbatim)
src/
  pipeline.py             the daily machine (run / publish-today / status /
                          dashboard / topup / prune)
  rotation.py             concept selection + repetition detection
  imagegen.py             Pollinations image generation (no key)
  background.py           white-background QC + watermark-zone repair
  validator.py            image QC (brightness, subject, OCR, watermark)
  video.py                FFmpeg 5s MP4 + ffprobe validation
  publisher.py            official IG Graph API (container → publish)
  hosting.py              free public video hosting (GitHub Pages / catbox)
  dashboard.py            static dashboard.html (status, timeline, costs)
  llm_topup.py            optional free-LLM bank refill
database/
  bank/{A,B,C,D}.json     64 concepts + 8 formulas
  content.json            post states (resume point, errors, timeline)
  history.json            publish history (drives rotation)
generated/                today's image + mp4 (local)
media/videos/             committed copies served by GitHub Pages
captions/                 per-post caption .txt
logs/                     pipeline.log + notifications.md
tests/test_pipeline.py    34-check test suite (10 scenarios)
scripts/audit_bank.py     bank pre-flight audit (scene words, banned
                          clichés, hook lengths) — run after any bank edit
docs/                     setup guide, cost audit, full report
```

## Running it locally instead of GitHub Actions (optional)

Works on any Linux/macOS machine (Windows: WSL):

```bash
pip install -r requirements.txt
sudo apt install ffmpeg tesseract-ocr          # once
export IG_ACCESS_TOKEN=... IG_USER_ID=...
./run_daily.sh                                  # or: python src/pipeline.py run
```

Cron example (11:00 IST): `0 11 * * * cd /path/to/words_for_being && ./run_daily.sh`.
Note: GitHub Actions is the recommended home — it's free, always-on, and the
dashboard lives in the repo.

## Cost — the honest number

**₹0/month.** Everything is free tier or open source; the only "spend" is
your attention (dashboard glance + one button in SAFE MODE).
Per-component audit: [docs/cost_audit.md](docs/cost_audit.md).

## Known limitations (honest list)

See [docs/REPORT.md §Honest limitations](docs/REPORT.md). The short version:
token refresh once a month; dev-mode API = your own test account (which is
exactly your real account); free image model occasionally renders a grey
background (QC catches it, 7 retries + marginal fallback); static image (no
motion, by design); single font until you drop another .ttf in `fonts/`.
