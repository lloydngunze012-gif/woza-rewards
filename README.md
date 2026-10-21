# Woza Rewards

Pay today. Get more tomorrow. — Demo PWA for the FNB App of the Year Hackathon.

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

Lender view: append `/lender` to whichever base URL you use.

## Demo screenshots (local)

With the app running on port 8000:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python tools/screenshots.py
```

Outputs `screenshots/*.png` and `screenshots.zip`.

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
| GET | `/api/lender_view` | Bureau before/after summary |
