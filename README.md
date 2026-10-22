# Woza Rewards

Pay today. Earn tomorrow. — Demo PWA for the FNB App of the Year Hackathon.

**Disclaimer:** All data in this app is synthetic and for demonstration only.

## For judges (use this link)

**Do not use a laptop-only URL** (`127.0.0.1`) or **`http://0.0.0.0`** — those will not work on a phone.

Deploy once to **Render** (free tier) and share the **public HTTPS URL** Render gives you, for example:

`https://woza-rewards.onrender.com`

Judges open that link on any phone, tap **Try as Thandi**, and use the app. No Wi‑Fi or firewall setup required.

Quick deploy:

1. Push this repo to GitHub.
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint** → connect the repo (uses `render.yaml`), **or** **Web Service** with:
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (same as `Procfile`)
   - **Health check path:** `/api/health`
3. Copy the live **`.onrender.com`** URL into your submission.

After a cold start or redeploy, **Profile → Reset demo** restores the seeded Thandi state.

**Demo story:** Thandi is **Gold** with **36 on-time months** toward **Black** (48 months). Home shows a three-stop tier ladder (Silver · Gold · Black).

## Demo credentials

- Tap **Try as Thandi**, or enter any phone number (maps to **Thandi Mokoena**, `072 418 3390`).

## Run locally (development)

```bash
cd woza-rewards
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

**This PC only:**

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

→ [http://127.0.0.1:8000](http://127.0.0.1:8000)

**Same Wi‑Fi as your phone (LAN demo):** must bind **`0.0.0.0`**, not `127.0.0.1`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Windows shortcut:

```powershell
.\run.ps1
```

Then on the phone use `http://<Wi-Fi-IPv4-from-ipconfig>:8000` (e.g. `http://192.168.1.81:8000`). Allow Python through Windows Firewall if prompted.

### Slow on your phone?

| Cause | What you see | Fix |
|--------|----------------|-----|
| **Wrong URL** | Spinner / “Cannot reach server” | Use **`http://YOUR-PC-WIFI-IP:8000`**, not `127.0.0.1`. Run **`.\run.ps1`** (binds `0.0.0.0`). |
| **PC server asleep / not running** | Long wait, then error | Start **`.\run.ps1`** and keep the PC awake on Wi‑Fi. |
| **Render free tier** | 30–60s first load after idle | Use **HTTPS Render URL** for judges; expect cold starts. |
| **First visit** | Extra second for fonts + session check | **Second visit** is faster (service worker caches the app shell). |
| **Heavy tier card** | Brief pause after login | Card art is shared/cached now; pull latest + hard refresh once. |

## Demo screenshots (local)

With the app running on port 8000:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python tools/screenshots.py
```

Each run **clears** `screenshots/` first, then writes `screenshots/390/` and `screenshots/360/` (14 steps each: 01–13 plus 15_card_back), plus `screenshots/1280/14_desktop_1280.png`, and rebuilds `screenshots.zip`.

## API (JSON)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness check (Render / monitoring) |
| POST | `/api/login` | `{ "phone": "..." }` — session cookie |
| GET | `/api/me` | Full app state |
| POST | `/api/pay` | `{ "bill_id": 1 }` |
| POST | `/api/pay_all` | Pay all bills for current period |
| POST | `/api/grace` | `{ "bill_id": 1 }` |
| POST | `/api/redeem` | `{ "option": "cash", "points": 10000 }` |
| POST | `/api/reset` | Drop DB and reseed |
