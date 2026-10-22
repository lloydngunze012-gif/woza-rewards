# Woza Rewards

Pay today. Earn tomorrow. — Demo PWA for the FNB App of the Year Hackathon.

**Disclaimer:** All data in this app is synthetic and for demonstration only.

## Try it

Open [https://woza-rewards.onrender.com](https://woza-rewards.onrender.com), enter your name, and tap **Continue**.

## For judges

**Live demo:** [https://woza-rewards.onrender.com](https://woza-rewards.onrender.com)

Do **not** use a laptop-only URL (`127.0.0.1`) or **`http://0.0.0.0`** — those will not work on a phone. The LAN run below is for **development only**.

The instance runs on Render **Starter** (always on). No Wi‑Fi or firewall setup required.

After a redeploy, **Profile → Reset demo** restores the seeded Thandi state.

**Demo story:** Thandi is **Gold** with **36 on-time months** toward **Black** (48 months). Home shows a three-stop tier ladder (Silver · Gold · Black).

Redeploy (if needed):

1. Push this repo to GitHub.
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint** → connect the repo (uses `render.yaml`), **or** **Web Service** with:
   - **Build:** `pip install -r requirements.txt`
   - **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (same as `Procfile`)
   - **Health check path:** `/api/health`
   - **Plan:** Starter
3. Judges use **https://woza-rewards.onrender.com**.

## Demo credentials

- Enter your name and tap **Continue**. The seeded demo member is **Thandi Mokoena**.

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

**Same Wi‑Fi as your phone (LAN, development only):** judges should use the live URL above. For local device testing, bind **`0.0.0.0`**, not `127.0.0.1`:

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
| **Render URL** | App does not load on a phone | Use **https://woza-rewards.onrender.com**, not localhost or a LAN IP. |
| **First visit** | Extra second for fonts + session check | **Second visit** is faster (service worker caches the app shell). |
| **Heavy tier card** | Brief pause after login | Card art is shared/cached now; pull latest + hard refresh once. |

## Demo screenshots (local)

With the app running on port 8000:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python tools/screenshots.py
```

Each run **clears** `screenshots/` first, then writes `screenshots/390/` and `screenshots/360/` (14 steps each: 01–13 plus 15_card_back), plus `screenshots/1280/14_desktop_1280.png`, an isolation check that two browsers keep separate rent, and rebuilds `screenshots.zip`.

## API (JSON)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness check (Render / monitoring) |
| POST | `/api/login` | `{ "name": "..." }` — private demo copy + session cookie |
| GET | `/api/me` | Full app state |
| POST | `/api/pay` | `{ "bill_id": 1 }` |
| POST | `/api/pay_all` | Pay all bills for current period |
| POST | `/api/grace` | `{ "bill_id": 1 }` |
| POST | `/api/redeem` | `{ "option": "cash", "points": 10000 }` |
| POST | `/api/reset` | Reseed this session only (keeps the name) |
