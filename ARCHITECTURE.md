# Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     GITHUB ACTIONS  (free, 05:30 UTC = 11:00 IST)           │
│                                                                             │
│  ┌────────────┐    ┌─────────────────────────────────────────────────────┐  │
│  │ config.json│───▶│                      pipeline.py                    │  │
│  │  (central) │    │                                                     │  │
│  └────────────    │  1 CONCEPT ──────────────────────────────────────── │  │
│                    │     rotation.py: Originality Law                    │  │
│  ┌────────────┐    │     • no formula twice in a row                     │  │
│  │ database/  │    │     • no category streak                            │  │
│  │ bank/ A-D  │───▶│     • banned-cliché phrases rejected                │  │
│  │ 64 ideas   │    │     • repetition check vs last N published          │  │
│  │ history.json│   │                                                     │  │
│  │ content.json│  │  2 IMAGE ─────────────────────────────────────────── │  │
│  └────────────    │     imagegen.py → Pollinations (free, no key)       │  │
│                    │     up to 7 attempts, each QC-gated:                │  │
│                    │       validator.py  bg p75 corner ≥190              │  │
│                    │                       subject < top third           │  │
│                    │                       OCR text = 0 words            │  │
│                    │                       watermark zone = 0 words      │  │
│                    │     background.py  white-bg repair +                │  │
│                    │                     watermark-zone paint (dual-     │  │
│                    │                     polarity OCR)                   │  │
│                    │                                                     │  │
│                    │  3 VIDEO ─────────────────────────────────────────── │  │
│                    │     video.py → FFmpeg: 1080×1920, 5.000 s,          │  │
│                    │              h264 yuv420p, silent AAC 48 kHz,       │  │
│                    │              +faststart                             │  │
│                    │     ffprobe hard validation                         │  │
│                    │                                                     │  │
│                    │  4 CAPTION ───────────────────────────────────────── │  │
│                    │     formula-driven hook + 3–5 native hashtags       │  │
│                    │                                                     │  │
│                    │  5 PUBLISH ───────────────────────────────────────── │  │
│                    │     SAFE:  stop → READY_TO_PUBLISH                  │  │
│                    │     AUTO:  hosting.py → media/videos/ (git push)    │  │
│                    │              → wait Pages live                      │  │
│                    │     publisher.py → official Meta Graph API          │  │
│                    │              /media container (REELS)               │  │
│                    │              → poll FINISHED → /media_publish       │  │
│                    └──────────────┬──────────────────────────────────────┘  │
└───────────────────────────────────┼─────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────────┐
        ▼                           ▼                               ▼
┌──────────────┐         ┌──────────────────┐          ┌───────────────────────┐
│ GitHub Pages │         │  Instagram       │          │  State (committed)    │
│ media/videos │◀─fetch─ │  Reels feed      │          │  database/content.json│
│ <mp4>        │         │  (your account)  │          │  database/history.json│
└──────────────┘         └──────────────────┘          │  logs/pipeline.log     │
                                                       │  logs/notifications.md │
                                                       │  dashboard.html        │
                                                       └───────────────────────┘
```

### Failure & resume model

```
QUEUED → GENERATING → IMAGE_READY → VIDEO_READY → READY_TO_PUBLISH → PUBLISHED
   │        │              │              │               │
   └────────┴──────────────┴──────────────┴───────────────┘
                     any failure:
        status = FAILED (or RETRYING), error + retry count recorded,
        partial assets kept, NO second post for the same date.
        Next daily run resumes the SAME post from the failed stage.

        unrecoverable-by-machine → MANUAL_ACTION_REQUIRED
        + note in logs/notifications.md (the only times a human is paged).
```

### Key invariants (enforced in code, tested)

1. One post per date — date-locked ID `wfB-YYYYMMDD-NNN`; re-run = no-op.
2. PUBLISHED is immutable; permalink recorded once.
3. Resume never re-generates earlier stages (T9 proves the image is not
   re-rendered after a crash between image and publish).
4. QC gates every image; a failed QC attempt is logged with its reasons,
   and retry hints are injected into the next prompt.
5. Secrets only via environment/Actions secrets; none in source or repo.
