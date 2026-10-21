# Woza Rewards

Pay today. Get more tomorrow. — Demo PWA for the FNB App of the Year Hackathon.

**Disclaimer:** All data in this app is synthetic and for demonstration only.

## Demo credentials

- Open the app and tap **Try as Thandi**, or log in with any phone number (maps to demo user **Thandi Mokoena**, `072 418 3390`).

## Run locally

```bash
cd woza-rewards
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Lender view: [http://127.0.0.1:8000/lender](http://127.0.0.1:8000/lender).

## Demo screenshots (local)

With the app running on port 8000:

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python tools/screenshots.py
```

Outputs `screenshots/*.png` and `screenshots.zip`.

## Deploy on Render (free tier)

1. Push this repo to GitHub.
2. In Render, create a **Web Service** from the repo.
3. **Runtime:** Python 3.11.
4. **Build command:** `pip install -r requirements.txt`
5. **Start command:** use the `Procfile` (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
6. Deploy and share the public URL with judges.

SQLite persists on Render only for the lifetime of the instance; use **Reset demo** on Profile to reseed after restarts.

## API (JSON)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/login` | `{ "phone": "..." }` — session cookie |
| GET | `/api/me` | Full app state |
| POST | `/api/pay` | `{ "bill_id": 1 }` |
| POST | `/api/pay_all` | Pay all bills for current period |
| POST | `/api/grace` | `{ "bill_id": 1 }` |
| POST | `/api/redeem` | `{ "option": "cash", "points": 10000 }` |
| POST | `/api/reset` | Drop DB and reseed |
| GET | `/api/lender_view` | Bureau before/after summary |
