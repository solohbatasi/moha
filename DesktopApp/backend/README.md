# Zetech Learning API

Standalone FastAPI backend for the Windows desktop app. It owns email sign-in, user records, one-time access entitlements, and M-Pesa Buy Goods STK Push. PostgreSQL is the database. The desktop app only calls this API; Safaricom and SMTP credentials stay on the backend host.

## How access works

1. The app requests a short-lived email code. Codes expire, are stored only as keyed hashes, and have a resend delay and attempt limit.
2. Verifying a code creates or loads the account and returns a signed bearer token.
3. If that account has no successful payment, the app requests an STK Push using the phone number entered at checkout.
4. The server fixes the amount from `APP_PRICE_KES`, starts a `CustomerBuyGoodsOnline` request, receives Daraja's callback, and checks the checkout with Daraja before granting lifetime access.

## Local setup

Use Python 3.10 or newer. In PowerShell, from this directory:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

The example config is for local development. It uses PostgreSQL at `127.0.0.1:5432`, with a development-only username and password. Start a local PostgreSQL database using Docker Compose:

```powershell
docker compose up -d db
```

If PostgreSQL is already installed or hosted, skip Compose and set `DATABASE_URL` in `.env` to that database. Use the form `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`; URL-encode special characters in the username or password. Do not use the example development password outside a local machine.

Start PostgreSQL first, then edit `.env`. The example JWT value is deliberately rejected: replace it with a random secret of at least 32 characters. Before starting the API for the first time, create its tables from the checked-in Alembic migration:

```powershell
alembic upgrade head
```

The API can then start and serve `/health` without SMTP or Daraja settings, but email sign-in needs a working SMTP sender and payments need Daraja sandbox credentials plus a public HTTPS callback. Run:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The API docs are available at `/docs`; health check is `/health`. The desktop app points to `http://127.0.0.1:8000` by default. For a separately hosted backend, change `API_URL` in `DesktopApp/main.py` to the public HTTPS API origin before packaging the client.

### Local test sign-in

To skip email verification and payment while testing locally, set `TEST_MODE=true` in the backend `.env` and `CODILITY_TEST_MODE=true` in the desktop app's environment before launching it. The test password and bearer token default to `12345678`; set `TEST_PASSWORD` in the backend `.env` and `CODILITY_TEST_PASSWORD` for the desktop app to change the password. The backend only accepts test sign-ins and the test token from a loopback connection, and test mode is disabled unless `APP_ENV=development`. Leave it disabled for deployments.

For frontend work that does not need the backend, set `CODILITY_DEVMODE=true` before launching the desktop app. This opens the project workspace directly and skips the sign-in and payment screens. It is off by default; clear the variable or set it to `false` to restore the normal flow.

### Run the desktop app

Keep the API running. Open a second PowerShell window and run:

```powershell
cd H:\projects\moha\DesktopApp
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

If PowerShell blocks virtual-environment activation, skip activation and use `.venv\Scripts\python.exe` in place of `python` and `.venv\Scripts\python.exe -m pip` in place of `pip`. The desktop client already points to the local API at `http://127.0.0.1:8000`.

To check only that the backend starts, open `http://127.0.0.1:8000/health` and `http://127.0.0.1:8000/docs`. To complete sign-in, configure SMTP and request an email code in the desktop app. To complete the payment flow, use Daraja sandbox credentials and expose the callback route over a temporary public HTTPS tunnel; Safaricom cannot call a `127.0.0.1` address. The Daraja portal supports sandbox app simulation for development. The app's project-creation button also requires the VS Code `code` command to be on PATH.

## Configuration

Copy `.env.example` and set:

- `APP_PRICE_KES`: one-time amount in whole KES. The API ignores any price supplied by a client.
- `MPESA_ENV`: `sandbox` during development; `production` only after Daraja go-live approval.
- `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET`, and `MPESA_PASSKEY`.
- `MPESA_BUSINESS_SHORTCODE` and `MPESA_TILL_NUMBER`. For Buy Goods STK Push the store/head-office shortcode is sent as `BusinessShortCode`; the customer-facing till is sent as `PartyB`.
- `MPESA_CALLBACK_URL`: public HTTPS route `/api/payments/mpesa/callback`. Safaricom must be able to reach it directly.
- `SMTP_*`: an SMTP account allowed to send the login codes.
- `DATABASE_URL`: PostgreSQL connection string. For production, use a managed PostgreSQL database, TLS if required by the provider, and persistent backups.
- `CLIENT_ORIGINS`: comma-separated origins if a browser client is added. The current PySide desktop client is not subject to browser CORS.

## Database migrations

The initial schema is in `alembic/versions/0001_initial_tables.py`. Run `alembic upgrade head` once for a new database, and again after deploying each new migration. For a schema change, create a candidate with `alembic revision --autogenerate -m "describe change"`, review the generated file, then apply it with `alembic upgrade head`.

Earlier versions of this app called SQLAlchemy `create_all()` on startup. If that already created these tables in the target database, do not run the initial migration directly against those existing tables. First confirm they match the migration, then mark the baseline with `alembic stamp head`; this records the revision without changing tables. On a fresh database, use `alembic upgrade head` instead.

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

Deploy this folder as an API service with HTTPS, PostgreSQL, SMTP access, and environment secrets. There is no Python `public` directory; keep the code and `.env` outside `public_html`.

### cPanel note

Check whether your cPanel account has **Setup Python App** or **Application Manager**, and whether it has **PostgreSQL Databases**. PostgreSQL support is optional in cPanel and may need to be enabled by the host. The current app is FastAPI (ASGI); cPanel's standard Passenger Python instructions describe WSGI apps. Do not point Passenger directly at `app.main:app` as if it were Flask. Ask the host whether the account supports ASGI/Uvicorn apps. If it only supports Passenger/WSGI, an ASGI-to-WSGI adapter may be possible, but it needs a compatibility check with the async M-Pesa callback before relying on it.

If the host supports a persistent Uvicorn service, use an API subdomain such as `api.example.com`, run Uvicorn bound to localhost, and have the web server proxy HTTPS requests to it. Otherwise, use the host's supported Python application interface or deploy the API to a service that supports ASGI. In either case, expose `/api/payments/mpesa/callback` publicly over HTTPS, point the desktop app's `API_URL` at the public HTTPS API origin, and back up PostgreSQL because it contains user and payment records.
