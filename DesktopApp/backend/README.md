# Zetech Learning API

Standalone FastAPI backend for the Windows desktop app. It owns email sign-in, user records, one-time access entitlements, and M-Pesa Buy Goods STK Push. The desktop app only calls this API; Safaricom and SMTP credentials stay on the backend host.

## How access works

1. The app requests a short-lived email code. Codes expire, are stored only as keyed hashes, and have a resend delay and attempt limit.
2. Verifying a code creates or loads the account and returns a signed bearer token.
3. If that account has no successful payment, the app requests an STK Push using the phone number entered at checkout.
4. The server fixes the amount from `APP_PRICE_KES`, starts a `CustomerBuyGoodsOnline` request, receives Daraja's callback, and checks the checkout with Daraja before granting lifetime access.

## Local setup

Use Python 3.10 or newer. From this directory:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` before starting the API. Set a random `JWT_SECRET` with at least 32 characters, configure a real SMTP sender, and use Daraja sandbox credentials and callback URL while developing. Run:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The API docs are available at `/docs`; health check is `/health`. The desktop app points to `http://127.0.0.1:8000` by default. For a separately hosted backend, change `API_URL` in `DesktopApp/main.py` to the public HTTPS API origin before packaging the client.

## Configuration

Copy `.env.example` and set:

- `APP_PRICE_KES`: one-time amount in whole KES. The API ignores any price supplied by a client.
- `MPESA_ENV`: `sandbox` during development; `production` only after Daraja go-live approval.
- `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, and `MPESA_PASSKEY`.
- `MPESA_BUSINESS_SHORTCODE` and `MPESA_TILL_NUMBER`. For Buy Goods STK Push the store/head-office shortcode is sent as `BusinessShortCode`; the customer-facing till is sent as `PartyB`.
- `MPESA_CALLBACK_URL`: public HTTPS route `/api/payments/mpesa/callback`. Safaricom must be able to reach it directly.
- `SMTP_*`: an SMTP account allowed to send the login codes.
- `DATABASE_URL`: SQLite is convenient for local development. Use a managed PostgreSQL database for a multi-instance or production deployment, with persistent backups.
- `CLIENT_ORIGINS`: comma-separated origins if a browser client is added. The current PySide desktop client is not subject to browser CORS.

Never send credentials in chat, commit `.env`, or put Daraja keys in the desktop app. If credentials have already been shared outside the trusted backend environment, rotate them in Daraja.

## Routes

- `POST /api/auth/email/request` — `{ "email": "person@example.com" }`
- `POST /api/auth/email/verify` — `{ "email": "person@example.com", "code": "123456" }`
- `GET /api/me` — current account and whether lifetime access is paid
- `POST /api/payments/stk-push` — authenticated `{ "phone": "07..." }`
- `GET /api/payments/{payment_id}` — authenticated payment status for that account
- `POST /api/payments/mpesa/callback` — public Daraja callback; checks the checkout with Daraja before marking it paid

The callback is public because Daraja calls it. It grants access only after the callback's checkout ID matches a pending payment, Daraja's STK query returns success, and the callback amount and payer match the stored order. If Daraja's status query has a temporary error, the authenticated payment-status route retries it at most once every 20 seconds. Payment state updates are idempotent.

## Hosting checklist

Deploy this folder as an API service with HTTPS, persistent PostgreSQL, SMTP access, and environment secrets. Expose the callback path publicly. Point the desktop app's `API_URL` at that API. Run one API worker initially if using SQLite; use PostgreSQL before running multiple workers. Back up the database because it contains user and payment records.
