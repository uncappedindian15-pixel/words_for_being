# Setup guide (no programming required)

Total: ~45 minutes. You will create free accounts and paste two short codes
into GitHub. You never share your Instagram password anywhere.

## 0. What you need

- A Google account (for Gmail — free) — optional but handy
- ~1 hour of time
- Your existing @words.for.being Instagram account

## 1. GitHub (free)

1. Go to **github.com** → Sign up (free).
2. Click **+ → New repository** → name it `words_for_being` → **Private**
   (recommended) → Create.
3. Upload this project: **Add file → Upload files** → select all files
   (including `src/`, `config/`, `database/`, etc.) → Commit.
   (Alternative: `git init && git add . && git commit -m "wfb" &&
   git remote add origin <repo-url> && git push -u origin main` if you
   know git.)

## 2. Instagram side (free, official)

1. On Instagram (phone): **Settings → Account type and tools → Switch to
   professional account → Creator**.
2. Create a **Facebook Page** (free, facebook.com → Pages):
   - Name: whatever you like (e.g. "Words For Being").
   - In the Page: **Professional dashboard → Connected assets → Instagram →
     Connect** your @words.for.being account.
   This linking is what the official API uses. Your password is given
   directly to Meta inside the official login window — it is never typed
   into GitHub or this project.

## 3. Meta developer app + token (free, ~15 min)

1. Go to **developers.facebook.com** → log in with the Facebook account
   that owns the Page → **My Apps → Create App → Business**.
2. App name: "wfb" (anything). Inside the app: **Add products → Instagram →
   Set up** (follow the prompts; it links the Page).
3. **Generate a token** (Graph Explorer, official):
   - developers.facebook.com → **Graph Explorer**.
   - App: select your app. User: **Add yourself as a test user**
     (this is dev mode — no app review needed for your own account).
   - Permissions: add `instagram_business_basic` and
     `instagram_business_content_publish` → **Generate Access Token**.
   - Exchange it for a **long-lived token** (lasts 60 days):
     `GET https://graph.facebook.com/v25.0/oauth/access_token?grant_type=fb_exchange_token&client_id=<APP_ID>&client_secret=<APP_SECRET>&fb_exchange_token=<SHORT_TOKEN>`
     (APP_ID/APP_SECRET are under your app's **Settings → Basic**.)
   - Result: one long string = **`IG_ACCESS_TOKEN`**.
4. Get your **IG user ID** (one number):
   `GET https://graph.instagram.com/me?fields=id&access_token=<IG_ACCESS_TOKEN>`
   Result: `"id": "178414..."` = **`IG_USER_ID`**.

> **Every 60 days** the token expires (free-tier rule). Refresh takes 10
> minutes by repeating step 3. The machine *detects* the expiry (error 190),
> marks the post `MANUAL_ACTION_REQUIRED`, and tells you exactly what to do.

## 4. GitHub Pages (free video hosting, ~5 min)

Instagram's official API downloads the video from a public HTTPS URL. We
host it on your own free GitHub Pages:

1. Repo → **Settings → Pages** → Build and deployment →
   **Deploy from a branch** → branch `main`, folder `/ (root)` → Save.
2. Wait ~1 minute; your site is at
   `https://<your-username>.github.io/words_for_being/`.
3. Edit `config/config.json`:
   ```json
   "video_public_host": { "type": "github_pages",
     "base_url": "https://<your-username>.github.io/words_for_being/media/videos/" }
   ```
   Commit the change. (The machine auto-commits each new MP4 into
   `media/videos/` and waits for Pages to serve it before publishing.)

## 5. Repository secrets (~2 min)

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `IG_ACCESS_TOKEN` | the long-lived token from step 3 |
| `IG_USER_ID` | the number from step 3 |

(No password. No private content. The token is only ever used by the
machine to post through the official API.)

## 6. First run & go-live

1. Repo → **Actions** tab → workflow **"Daily Reel"** → **Run workflow**
   (button on the right).
2. Watch it (~3–8 min): concept → image (7 QC attempts max) → MP4 →
   caption → stop at **READY_TO_PUBLISH** (SAFE MODE is the default).
3. Open `dashboard.html` in the repo (Settings → Pages URL, or simply click
   the file in GitHub — the HTML preview renders).
4. Happy with today's post? Actions → **"Publish Today (SAFE MODE
   button)"** → **Run workflow**. Check your Instagram.
5. Done. From tomorrow 11:00 IST it runs by itself.

### Switching to AUTO MODE (fully hands-off)

When you trust it: open `config/config.json`, set `"mode": "AUTO"`, commit.
The daily workflow will then publish automatically. You can revert to SAFE
at any time (the same file, one word).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR 190` in Actions log | token expired → refresh (step 3) → Actions → "Publish Today" |
| `ERROR 10/200` (publish) | IG rejected the container — usually a 24 h rate cap or a rejected file; wait an hour and click "Publish Today" again (video is already staged, no re-generation) |
| Post stuck `MANUAL_ACTION_REQUIRED` | read `logs/notifications.md` — it contains the exact instruction |
| Image keeps failing QC | normal on a bad day: 7 attempts + marginal fallback; if a whole day is lost, tomorrow's run resumes it automatically |
| Pages URL 404 for >10 min | re-check Pages settings (step 4); click "Publish Today" again — it re-waits for the URL |
