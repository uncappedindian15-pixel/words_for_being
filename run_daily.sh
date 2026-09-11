#!/usr/bin/env bash
# words.for.being — run today's pipeline locally (optional; GitHub Actions
# is the recommended home). Requires: python3, ffmpeg, tesseract, and env
# vars IG_ACCESS_TOKEN / IG_USER_ID (see docs/setup-instagram.md).
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found. Install it once: sudo apt install ffmpeg (or: pip install imageio-ffmpeg)" >&2
  exit 1
fi

export WFB_LOCAL=1
python3 src/pipeline.py run "$@"
echo
echo "Status: "
python3 src/pipeline.py status
