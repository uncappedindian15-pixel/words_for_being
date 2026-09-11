"""Free public video hosting so Instagram's servers can fetch the MP4.

Instagram's Graph API requires a public HTTPS URL for the MP4 (it downloads
the file itself; there is no file upload in the standard flow).

Default: type "github_pages" (self-hosted, permanent, ₹0)
  1. copies the MP4 to media/videos/<name>.mp4 in this repo
  2. commits + pushes it (token from WFB_GIT_TOKEN, or GITHUB_TOKEN on
     GitHub Actions where it is provided automatically)
  3. waits for the GitHub Pages URL to go live (deploy takes 1-5 minutes),
     then hands the URL to the publisher
  If no token is available the file is staged in media/videos/ and the
  pipeline stops at MANUAL_ACTION_REQUIRED with clear instructions
  (push the file, then: python src/pipeline.py publish-today).

Alternative: type "catbox" — instant third-party host (works from home
connections; some datacenter IPs are blocked by catbox). Files expire when
deleted by the service; only used at publish time, so fine in practice.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import requests

import common


class HostError(Exception):
    pass


def _log(logger, msg):
    (logger or print)(msg)


def _git(cwd: Path, args: list, token: str | None = None, remote: str | None = None):
    env = dict(os.environ)
    if token and remote:
        args = ["-c", f"http.extraHeader=Authorization: token {token}", *args]
        args = [remote.replace("https://", f"https://{token}@"), *args]
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env, timeout=300)
    if p.returncode != 0:
        raise HostError(f"git {' '.join(args[:3])} failed: {(p.stderr or p.stdout)[:300]}")
    return p.stdout.strip()


def _push_video_to_repo(cfg: dict, video_path: Path, url: str, logger) -> None:
    """Copy into media/videos/, commit + push, wait for Pages to serve it."""
    root = common.ROOT
    media = root / "media" / "videos"
    media.mkdir(parents=True, exist_ok=True)
    dest = media / video_path.name
    if not dest.exists() or dest.stat().st_size != Path(video_path).stat().st_size:
        shutil.copyfile(video_path, dest)
        _log(logger, f"hosting: staged video at media/videos/{dest.name}")

    branch = cfg["github"].get("branch", "main")
    repo = os.environ.get("GITHUB_REPOSITORY") or (
        f"{cfg['github'].get('owner', '')}/{cfg['github'].get('repo', '')}"
    )
    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    token = os.environ.get("WFB_GIT_TOKEN") or (os.environ.get("GITHUB_TOKEN") if in_actions else None)

    if token and repo and "YOUR_GITHUB_USERNAME" not in repo:
        subprocess.run(["git", "config", "user.email", "wfb-bot@users.noreply.github.com"],
                       cwd=str(root), capture_output=True)
        subprocess.run(["git", "config", "user.name", "wfb-bot"], cwd=str(root), capture_output=True)
        p = subprocess.run(
            ["git", "add", f"media/videos/{dest.name}"], cwd=str(root), capture_output=True, text=True
        )
        if p.returncode == 0 and not subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=str(root)
        ).returncode == 0:
            subprocess.run(
                ["git", "commit", "-m", f"wfb: video {dest.name}"],
                cwd=str(root), capture_output=True, text=True,
            )
        if in_actions:
            _git(root, ["push", "origin", f"HEAD:{branch}"])
        else:
            _git(root, ["push", f"https://{token}@github.com/{repo}.git", f"HEAD:{branch}"],
                 token=token)
        _log(logger, "hosting: pushed video to GitHub (Pages deploy in progress)")
    else:
        raise HostError(
            f"video staged at media/videos/{dest.name} but no git token available "
            "(set WFB_GIT_TOKEN, or run on GitHub Actions). Push it manually, then: "
            "python src/pipeline.py publish-today"
        )

    if os.environ.get("WFB_SKIP_URL_WAIT") == "1":
        return url
    _log(logger, f"hosting: waiting for Pages URL to go live: {url}")
    for i in range(96):  # up to 8 minutes
        try:
            r = requests.head(url, timeout=30, allow_redirects=True)
            if r.status_code == 200:
                _log(logger, "hosting: URL is live")
                return url
        except Exception:
            pass
        time.sleep(5)
    raise HostError(f"video URL not live after 8 minutes (Pages deploy delay?): {url}")


def host_video(cfg: dict, video_path: Path, logger=None) -> str:
    host = cfg["instagram"]["video_public_host"]
    t = host.get("type", "github_pages")
    video_path = Path(video_path)

    if t == "catbox":
        with open(video_path, "rb") as fh:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (video_path.name, fh, "video/mp4")},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"},
                timeout=300,
            )
        url = r.text.strip()
        if not url.startswith("https://"):
            raise HostError(f"catbox upload failed (HTTP {r.status_code}): {r.text[:200]}")
        return url

    if t == "github_pages":
        base = host.get("base_url", "")
        if not base or "YOUR_GITHUB_USERNAME" in base:
            raise HostError(
                "video_public_host.base_url not configured — set your GitHub Pages URL "
                "in config/config.json (https://<you>.github.io/<repo>/media/videos/)"
            )
        url = base.rstrip("/") + "/" + video_path.name
        return _push_video_to_repo(cfg, video_path, url, logger)

    raise HostError(f"unknown video_public_host.type: {t}")
