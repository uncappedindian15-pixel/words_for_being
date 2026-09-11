# Cost audit — component by component

Target: **₹0/month**, no card required, no trial-that-becomes-billing.

| # | Component | What it does | Provider | Free status | Free-tier limit | Card needed? | Open-source alternative exists? | ₹/month |
|---|-----------|--------------|----------|-------------|-----------------|--------------|--------------------------------|---------|
| 1 | Scheduling + compute | runs the pipeline daily | GitHub Actions | **100% Free** | 2,000 min/mo (public & private repos); we use ~10 min/day ≈ 300/mo | No | yes (self-hosted runner) | **0** |
| 2 | Image generation | 1 image/post | Pollinations (pollinations.ai) | **Free With Limits** | anon tier: no key, ~1 img/15 s, 576×1024 (we upscale), soft rate limit (429 → 20 s sleep) | No | partial (local Stable Diffusion — needs GPU) | **0** |
| 3 | Image QC + watermark repair | brightness, subject placement, OCR, watermark-zone paint | Pillow + numpy + scipy + Tesseract | **100% Free** (open source, runs on the Actions runner) | unlimited | No | it IS the OSS option | **0** |
| 4 | Video rendering | static 5 s MP4 | FFmpeg | **100% Free** (open source) | unlimited | No | it IS the OSS option | **0** |
| 5 | Video validation | ffprobe hard gate | FFmpeg | **100% Free** | unlimited | No | — | **0** |
| 6 | Public video URL | Instagram must fetch the MP4 | **GitHub Pages** (self-hosted on your repo) | **100% Free** | 100 GB storage + 100 GB/mo bandwidth; videos are ~170 KB each ≈ 5 MB/mo | No | yes (any static host) | **0** |
| 6b | (alternative) public URL | — | catbox.moe | Free With Limits | no account/key; files deleted by service after a while; some datacenter IPs blocked | No | — | 0 |
| 7 | Publishing | Reels post | Meta Instagram Graph API (official) | **100% Free** (API itself is free; this is the only sanctioned free method) | ~25 Reels/24 h in dev mode (we post 1/day); dev mode = test users only (your own account) | No | none (this is the official path; browser bots violate IG ToS) | **0** |
| 8 | Content memory + state | bank, history, post states | JSON files committed to the repo | **100% Free** (GitHub repo storage) | 1 GB repo; content files are KB-sized | No | — | **0** |
| 9 | Dashboard | status observability | static HTML committed to repo + GitHub web UI | **100% Free** | — | No | — | **0** |
| 10 | Notifications | "human needed" alerts | Actions run-status email + `logs/notifications.md` + dashboard | **100% Free** | — | No | — | **0** |
| 11 | Bank top-up (optional, ~monthly) | new concepts when bank runs low | Google AI Studio (Gemini) free tier | **Free With Limits** | free key, hundreds of requests/day, no card | No | any free LLM endpoint (the `topup` command takes a provider flag) | **0** |
| 12 | Fonts | typography | Google Fonts (Anton, OFL license) | **100% Free** | — | No | — | **0** |

**Total: ₹0/month.** No component requires a credit card, and nothing
"free" is a trial that converts to paid.

### The three honest caveats

1. **Pollinations anon tier is a favour, not a contract.** It can change
   rate limits or shut down. Mitigation baked in: 7 QC retries with
   different seeds, 429-aware backoff, and `imagegen.py` has a provider
   flag — swapping in another free keyless endpoint is a 10-line change.
2. **GitHub free tier** is generous but not unlimited (2,000 min/mo,
   1 GB repo, 100 GB Pages bandwidth). This machine uses ~300 min/mo and
   ~5 MB/mo of video. You would need ~7× the current usage to hit a wall.
3. **IG dev mode** limits the app to *test users* — which is exactly your
   own account, so no impact. If Meta ever requires app review for a
   personal creator to self-post, that is a platform policy change outside
   our control; the code would not change, only the Meta console steps.
