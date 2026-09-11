"""Observability dashboard — renders database/content.json into a single
self-contained HTML file (inline CSS, no network, works offline)."""
from __future__ import annotations

import html
from datetime import datetime

import common
import rotation

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#F7F4EE;color:#17150F;padding:28px}
.wrap{max-width:880px;margin:0 auto}
h1{font-size:22px;letter-spacing:.5px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:1.5px;color:#8a8578;margin:26px 0 10px}
.card{background:#fff;border:1px solid #e7e2d6;border-radius:12px;padding:16px 18px;margin-bottom:12px}
.row{display:flex;gap:12px;flex-wrap:wrap}
.stat{flex:1;min-width:120px;background:#fff;border:1px solid #e7e2d6;border-radius:12px;padding:14px 16px}
.stat .n{font-size:26px;font-weight:700}
.stat .l{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#8a8578}
.step{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:14px}
.step .ic{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;color:#fff;flex:0 0 22px}
.ok .ic{background:#3f7d4e}.no .ic{background:#b0432f}.wait .ic{background:#cfc9bb}.skip .ic{background:#e7e2d6}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#8a8578;padding:6px 8px;border-bottom:1px solid #e7e2d6}
td{padding:7px 8px;border-bottom:1px solid #f0ece2;vertical-align:top}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:600}
.p-PUBLISHED{background:#e2efe4;color:#2c5e3a}.p-READY_TO_PUBLISH{background:#fdf3d7;color:#8a6d1a}
.p-FAILED{background:#f9e2dc;color:#8c2f1d}.p-MANUAL_ACTION_REQUIRED{background:#f9e2dc;color:#8c2f1d}
.p-RETRYING{background:#e8eefb;color:#2f4f8c}.p-QUEUED,.p-GENERATING,.p-IMAGE_READY,.p-VIDEO_READY{background:#eee;background:#eceae4;color:#555}
.muted{color:#8a8578;font-size:12px}
a{color:#2f4f8c;text-decoration:none}
.err{font-size:12px;color:#8c2f1d;margin-top:6px}
.mode{font-size:11px;padding:2px 10px;border-radius:999px;background:#eceae4;margin-left:8px;vertical-align:middle}
"""

STEPS = [
    ("concept", "Concept generated"),
    ("image", "Image generated"),
    ("qc", "Quality checked"),
    ("video", "MP4 created"),
    ("caption", "Caption created"),
    ("publish", "Published"),
]


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _step_state(post, key):
    """Return 'ok' | 'no' | 'wait' based on timeline/status."""
    st = post["status"]
    if key == "concept":
        return "ok" if post.get("concept") else ("no" if st in ("FAILED", "MANUAL_ACTION_REQUIRED") else "wait")
    if key == "image":
        return "ok" if post.get("image") else ("no" if st in ("FAILED", "MANUAL_ACTION_REQUIRED") and any("image" in e for e in post.get("errors", [])) else "wait")
    if key == "qc":
        return "ok" if post.get("image") and post.get("video") else "wait"
    if key == "video":
        return "ok" if post.get("video") else ("no" if any("video" in e for e in post.get("errors", [])) else "wait")
    if key == "caption":
        return "ok" if post.get("caption") else "wait"
    if key == "publish":
        if st == "PUBLISHED":
            return "ok"
        if st in ("FAILED", "MANUAL_ACTION_REQUIRED", "RETRYING") and post.get("publish") is not None:
            return "no"
        if st == "READY_TO_PUBLISH":
            return "wait"
        return "wait"


def _today_card(cfg, db):
    today = common.today_ist()
    post = common.get_post_by_date(db, today)
    rows = []
    if post is None:
        msg = (f'<div class="muted">No post yet for today — the next scheduled run will create it '
               f'(daily at {cfg["schedule"]["posting_time_ist"]} IST).</div>')
        return (f'<div class="card"><h2 style="margin-top:0">Today&#39;s post — {today}</h2>{msg}</div>')
    icon = {"ok": "✓", "no": "✕", "wait": "·", "skip": "–"}
    steps_html = []
    for key, label in STEPS:
        state = _step_state(post, key)
        steps_html.append(f'<div class="step {state}"><div class="ic">{icon[state]}</div><div>{label}</div></div>')
    c = post.get("concept") or {}
    link = (f'<a href="{_esc(post["publish"]["permalink"])}" target="_blank">open on Instagram ↗</a>'
            if (post.get("publish") or {}).get("permalink") else "")
    err = post["errors"][-1] if post["errors"] else ""
    rows_html = "".join(steps_html)
    hook = f'<div style="margin-top:8px"><b>“{_esc(c.get("hook"))}”</b> <span class="muted">({_esc(c.get("id"))} · cat {_esc(c.get("category"))} · formula {_esc(c.get("formula"))})</span></div>'
    return (f'<div class="card"><h2 style="margin-top:0">Today\'s post — {today}</h2>'
            f'{rows_html}{hook}'
            f'<div class="muted" style="margin-top:8px">status: {_esc(post["status"])} · retries: {_esc(post.get("retries_total", 0))} · {link}</div>'
            + (f'<div class="err">last error: {_esc(err)}</div>' if err else "")
            + "</div>")


def _stats(db):
    posts = db["posts"]
    total = len(posts)
    published = sum(1 for p in posts if p["status"] == "PUBLISHED")
    failed = sum(1 for p in posts if p["status"] == "FAILED")
    manual = sum(1 for p in posts if p["status"] == "MANUAL_ACTION_REQUIRED")
    retries = sum(p.get("retries_total", 0) for p in posts)
    return total, published, failed, manual, retries


def _recent_table(db):
    posts = sorted(db["posts"], key=lambda p: p["date"], reverse=True)[:12]
    if not posts:
        return '<div class="muted">no posts yet</div>'
    rows = []
    for p in posts:
        c = p.get("concept") or {}
        perm = (p.get("publish") or {}).get("permalink")
        link = f'<a href="{_esc(perm)}" target="_blank">↗</a>' if perm else ""
        rows.append(
            "<tr>"
            f"<td>{_esc(p['date'])}</td>"
            f"<td>{_esc(p['post_id'])}</td>"
            f"<td>{_esc(c.get('category'))}</td>"
            f"<td>{_esc(c.get('formula'))}</td>"
            f"<td>{_esc((c.get('hook') or '')[:60])}</td>"
            f'<td><span class="pill p-{_esc(p["status"])}">{_esc(p["status"])}</span> {link}</td>'
            f"<td>{_esc(p.get('retries_total', 0))}</td>"
            "</tr>"
        )
    head = ("<tr><th>date</th><th>post id</th><th>cat</th><th>formula</th>"
            "<th>hook</th><th>status</th><th>retries</th></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def _failed(db):
    bad = [p for p in db["posts"] if p["status"] in ("FAILED", "MANUAL_ACTION_REQUIRED")]
    if not bad:
        return '<div class="muted">none 🎉</div>'
    out = []
    for p in bad[-5:]:
        err = p["errors"][-1] if p["errors"] else "(no error logged)"
        out.append(f'<div class="card"><b>{_esc(p["post_id"])}</b> <span class="muted">{_esc(p["date"])}</span> '
                   f'<span class="pill p-{_esc(p["status"])}">{_esc(p["status"])}</span>'
                   f'<div class="err">{_esc(err)}</div></div>')
    return "".join(out)


def _next_run(cfg, db):
    today = common.today_ist()
    t = cfg["schedule"]["posting_time_ist"]
    if common.get_post_by_date(db, today) and common.get_post_by_date(db, today)["status"] == "PUBLISHED":
        from datetime import timedelta
        nxt = (datetime.now(common.IST) + timedelta(days=1)).date().isoformat()
        return f"tomorrow ({nxt}) at {t} IST"
    return f"today ({today}) at {t} IST"


def render(cfg: dict, db: dict) -> None:
    today = common.today_ist()
    total, published, failed, manual, retries = _stats(db)
    last_pub = None
    for p in sorted(db["posts"], key=lambda p: p.get("created", ""), reverse=True):
        if p["status"] == "PUBLISHED":
            last_pub = f'{p["date"]} · {p["post_id"]}'
            break
    token_at = (db.get("meta") or {}).get("token_verified_at", "never verified")
    mode = cfg["instagram"]["mode"].upper()
    html_doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>words.for.being — status</title><style>{CSS}</style></head><body><div class="wrap">
<h1>words.for.being <span class="mode">{_esc(mode)}</span></h1>
<div class="muted">rendered {common.now_ist().isoformat(timespec='seconds')} IST · next run: {_esc(_next_run(cfg, db))} · IG token last verified: {_esc(token_at)}</div>
{_today_card(cfg, db)}
<h2>Stats</h2>
<div class="row">
<div class="stat"><div class="n">{total}</div><div class="l">posts generated</div></div>
<div class="stat"><div class="n">{published}</div><div class="l">posts published</div></div>
<div class="stat"><div class="n">{failed + manual}</div><div class="l">failed / manual</div></div>
<div class="stat"><div class="n">{retries}</div><div class="l">total retries</div></div>
</div>
<h2>Needs attention</h2>
{_failed(db)}
<h2>Recent posts</h2>
<div class="card" style="padding:6px 10px">{_recent_table(db)}</div>
<div class="muted" style="margin-top:18px">last successful post: {_esc(last_pub or '—')} · data: database/content.json · errors: logs/notifications.md</div>
</div></body></html>"""
    out = common.ROOT / "dashboard.html"
    out.write_text(html_doc, encoding="utf-8")
    return out
