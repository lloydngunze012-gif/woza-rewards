# Security

Woza Rewards is a synthetic hackathon demo. This note is the SSDLC summary for reviewers.

## Secrets

`SECRET_KEY` and `DEMO_PASSWORD` are read from the environment (`app/config.py`) with safe local defaults. Copy `.env.example` to `.env` for local overrides. `.env` is gitignored.

- `SECRET_KEY` signs the `woza_session` cookie (HMAC-SHA256). The unsigned session id is stored server-side; a forged cookie is rejected.
- `DEMO_PASSWORD` is reserved for operator / partner tooling. The consumer UI never collects or sends it.
- Render generates both values via `render.yaml` (`generateValue: true`).

## HTTP headers

Every response includes:

- `Content-Security-Policy` — `default-src 'self'`, plus `fonts.googleapis.com` and `fonts.gstatic.com` for type. Inline script/style remain `'unsafe-inline'` because the PWA shell is a single HTML file.
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`

## Rate limiting

slowapi limits `/api/*` to **60 requests per minute per IP**. Static assets and HTML are not counted toward that budget.

## Input validation

Every POST body is a Pydantic model with `extra="forbid"`. Amounts must be `> 0`. Period fields must match `YYYY-MM`.

## Partner APIs

`GET /api/lender_view` and `GET /api/forecast` require a valid signed demo session cookie. Unauthenticated calls return **401**. There is no public lender HTML surface in this build.

## XSS

The front end does not interpolate API strings into `innerHTML` unescaped. User- and API-derived text is HTML-escaped before it is inserted into the DOM. Membership-card names use the same rule.

## Data minimisation

The demo stores only a first name (display), a synthetic phone on the seeded profile, bill rows, points, and a session key. No ID number, no real account number, no live bank credentials. Linked-bank copy is a static demo label (`FNB Cheque ••4821`).

## Synthetic demo data

All balances, bills, scores, and history are seeded fiction for the FNB App of the Year demo. No real money moves. See the in-app “Demo mode” note and the README disclaimer.

## Consent before bank feed

Car-finance verification is modelled as a **bank debit-order read** and is gated on `bank_consent_active`. Home gear → Linked bank → **Revoke consent** turns verification off. Woza never initiates a debit from that account in this demo.

## AI disclosure (forecast)

`GET /api/forecast` is Woza Forecast, a rules-based model (`method: woza_forecast_rules`). Every response includes `disclosure`: *Predicted by Woza Forecast, a rules-based model. Woza does not make credit decisions; a human at the lender does.* It is **not** a credit decision and **not** a production ML model.

## Third-party inventory

| Party | Purpose | Data sent |
|-------|---------|-----------|
| Render | Hosting (Oregon starter) | HTTPS traffic; env secrets stay on the instance |
| Google Fonts (`fonts.googleapis.com`, `fonts.gstatic.com`) | Sora + DM Sans | Page origin only (no member payload) |
| SQLite (`woza.db`) | Local demo state | On-instance only; purged after 7 days of inactivity |

No live bureau, bank, or payments processors are connected. Redemptions and pay flows update the local demo database only.

## Session

HttpOnly `SameSite=Lax` cookie, 7-day max-age, HMAC-signed with `SECRET_KEY`. `/api/logout` and **Sign out** clear it. **Reset demo** reseeds that session only.
