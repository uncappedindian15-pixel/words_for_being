"""Instagram publishing via the official Meta Graph API (free, legitimate).

Flow (official Reels publishing):
  1. POST /{ig-user-id}/media        media_type=REELS, video_url, caption
  2. poll  /{container-id}?fields=status_code  until FINISHED
  3. POST /{ig-user-id}/media_publish  creation_id
  4. GET  /{container-id}?fields=permalink,caption  (verify)

Requirements (free, one-time setup — see README):
  - Instagram Professional account (Creator or Business)
  - Meta developer app with Instagram product
  - long-lived access token (60 days; refresh monthly or use a System User)
  - the MP4 must be reachable at a public HTTPS URL (GitHub Pages works free)

Secrets: token comes from env IG_ACCESS_TOKEN (never in code, never in git).
Test hook: env WFB_MOCK_BASE points the client at a local mock server.
"""
from __future__ import annotations

import os
import time

import requests


class PublisherError(Exception):
    pass


class IGPublisher:
    def __init__(self, cfg: dict, token: str | None = None, base_url: str | None = None):
        g = cfg["instagram"]
        self.mock_base = os.environ.get("WFB_MOCK_BASE")
        if self.mock_base:
            self.base = self.mock_base.rstrip("/")
        else:
            self.base = f"{g['graph_base_url'].rstrip('/')}/{g['graph_api_version']}"
        self.token = token or os.environ.get("IG_ACCESS_TOKEN")
        self.ig_user_id = os.environ.get("IG_USER_ID") or g.get("ig_user_id") or None
        self.session = requests.Session()

    # ---------- low level ----------
    def _check(self, r: requests.Response):
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:400]}
        if r.status_code >= 400 or isinstance(body, dict) and "error" in body:
            err = body.get("error") if isinstance(body, dict) else {}
            if isinstance(err, dict):
                msg, code = err.get("message"), err.get("code")
                hint = err.get("error_user_msg", "")
            else:
                msg, code, hint = str(err), None, ""
            raise PublisherError(f"IG API HTTP {r.status_code} code={code} {hint} :: {msg}")
        return body

    def get(self, path: str, **params):
        if self.mock_base:
            p = dict(params)
        else:
            if not self.token:
                raise PublisherError("IG_ACCESS_TOKEN env var is missing")
            p = {**params, "access_token": self.token}
        r = self.session.get(self.base + path, params=p, timeout=60)
        return self._check(r)

    def post(self, path: str, data: dict | None = None, **params):
        if self.mock_base:
            p = dict(params)
        else:
            if not self.token:
                raise PublisherError("IG_ACCESS_TOKEN env var is missing")
            p = {**params, "access_token": self.token}
        r = self.session.post(self.base + path, data=data, params=p, timeout=120)
        return self._check(r)

    # ---------- flow ----------
    def verify_token(self) -> dict:
        """Lightweight token/account check."""
        r = self.get("/me", fields="id,username")
        if self.ig_user_id is None:
            self.ig_user_id = r.get("id")
        return r

    def create_reel(self, video_url: str, caption: str, cover_url: str | None = None) -> str:
        data = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true" if self.cfg_share() else "false",
        }
        if cover_url:
            data["cover_url"] = cover_url
        r = self.post(f"/{self.ig_user_id}/media", data=data)
        if not r.get("id"):
            raise PublisherError(f"media creation returned no id: {r}")
        return r["id"]

    def cfg_share(self) -> bool:
        # publisher holds a reference set by pipeline when constructed via
        # make_publisher(cfg); kept simple: default True
        return getattr(self, "_share", True)

    def wait_processing(self, media_id: str, timeout: int = 300, poll: int = 5) -> dict:
        start = time.time()
        last = {}
        while time.time() - start < timeout:
            last = self.get(f"/{media_id}", fields="status_code,status")
            st = last.get("status_code")
            if st in ("FINISHED", "PUBLISHED"):
                return last
            if st in ("ERROR", "FAILED"):
                raise PublisherError(f"container processing failed: {last}")
            time.sleep(poll)
        raise PublisherError(f"timeout ({timeout}s) waiting for container {media_id}; last={last}")

    def publish(self, creation_id: str) -> dict:
        r = self.post(f"/{self.ig_user_id}/media_publish", data={"creation_id": creation_id})
        return r

    def verify(self, media_id: str) -> dict:
        return self.get(f"/{media_id}", fields="permalink,code,caption,status_code")


def make_publisher(cfg: dict, token: str | None = None, base_url: str | None = None) -> IGPublisher:
    pub = IGPublisher(cfg, token=token, base_url=base_url)
    pub._share = bool(cfg["instagram"].get("share_to_feed", True))
    return pub
