# Bonjour Bakery - Management & E-commerce Platform

Python **FastAPI** backend (SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL) with a **vanilla HTML/CSS/JS** installable PWA frontend (no frameworks, no build step).

* Customer storefront: `/` (browse, cart, guest or account checkout, order tracking, reorder)
* Staff console: `/#/staff` (role-aware: dashboard, branches, orders, customers, payments, products, production, inventory, suppliers, purchasing, dispatch, drivers, vehicles, finance, expenses, reports, staff & roles, tasks, audit logs, settings)
* Driver app: drivers who sign in at `/#/staff` get a mobile-first app showing only their own deliveries
* API docs: `/docs` (disabled in production)

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit SECRET_KEY, DATABASE_URL, ADMIN_*
alembic upgrade head            # creates all tables
uvicorn app.main:app --reload   # http://localhost:8000
```

**First admin (recommended):** set `SETUP_KEY` to a long secret, deploy, then open `/#/setup`, enter your name, email, password and the setup key. This works only while the database has no users and closes permanently once the first admin exists; then remove `SETUP_KEY`. (Alternatively set `ADMIN_EMAIL`/`ADMIN_PASSWORD` and the admin is created on startup.)

**Locked out / forgot the admin password (no shell needed):** set `ADMIN_EMAIL`, `ADMIN_PASSWORD` and `ADMIN_RESET=true`, redeploy once, sign in, then delete `ADMIN_RESET` and `ADMIN_PASSWORD`.

On startup the app idempotently seeds permissions, the 12 roles, production stages, expense/product categories and the Super Admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Change that password after first sign-in. `python -m app.create_admin` creates/resets an admin manually.

### Demo data (kept separate from live data)
```bash
python -m app.seed demo --password DemoPass2026   # sample branches, staff, products, orders, finance, production, dispatch
python -m app.seed purge                          # removes every demo record
```
Demo rows are flagged `is_demo` and are only visible while *Settings → Data mode* is `demo`. Demo staff logins look like `demo.general_manager@bonjour-demo.com`, `demo.accountant@bonjour-demo.com`, `demo.driver10@bonjour-demo.com`. Never run demo mode on a live database you care about without purging first.

## Environment variables
See `.env.example`. Key ones: `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL` (postgres:// URLs are converted automatically), `COOKIE_SECURE=true` (HTTPS), `PUBLIC_BASE_URL`, `UPLOAD_DIR`, `PAYSTACK_SECRET_KEY` / `PAYSTACK_PUBLIC_KEY`, optional `SMTP_*`, `SMS_PROVIDER_KEY`, `WHATSAPP_PROVIDER_KEY`.

## Deployment (Render / Railway / Heroku-style)
* Build: `pip install -r requirements.txt`. Start (see `Procfile`): `alembic upgrade head && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:$PORT`
* Provision PostgreSQL and set `DATABASE_URL`. Set `APP_ENV=production`, a long random `SECRET_KEY`, `ADMIN_*`, `COOKIE_SECURE=true`.
* **Uploads** (payment proofs, product images, expense receipts) are written to `UPLOAD_DIR`. On hosts with ephemeral disks, mount a persistent volume there.
* Serve over HTTPS; the app sets HSTS, CSP, frame, referrer and nosniff headers.

## Paystack
Set `PAYSTACK_SECRET_KEY` (and public key). Online payment is offered only when configured. A payment is **never** marked paid from the browser: the server verifies the transaction with Paystack (callback verify and signed webhook at `/api/public/paystack/webhook`, HMAC-SHA512) and checks reference, amount and currency before posting revenue. Point the Paystack dashboard webhook to that URL. Not exercised against live Paystack in this build (no keys available) - test with Paystack test keys before go-live.

## Security model
* Argon2 password hashing; DB-backed sessions in HttpOnly SameSite cookies; double-submit CSRF token on all writes; login lockout (5 failures → 15 min); in-process rate limiting (use a shared limiter if you scale beyond one process); sessions revoked on password/role/permission change or deactivation.
* RBAC enforced on the server for every endpoint, with per-user permission overrides and branch isolation (branch staff only see their branches; drivers only their own deliveries).
* Money is stored as integer kobo; stock changes only through one locked, audited path and can never go negative; ledger entries are immutable; revenue posts only on *verified* payments; expenses over the threshold need approval by someone else.
* Uploads: type sniffed by magic bytes, 3 MB limit, random file names. Audit log records sign-ins, status changes, approvals, adjustments and settings changes.
* Email/SMS/WhatsApp: in-app notifications work; external channels are structured and queue as `not_configured` until provider credentials are supplied - nothing is claimed as sent.

## Tests
```bash
export TEST_DATABASE_URL=postgresql+psycopg://user@host/bonjour_test   # an empty, disposable DB
python -m pytest tests -q          # 34 tests: auth, RBAC, branch isolation, order lifecycle, stock, payments, finance, production, dispatch, procurement
```

## PWA
`manifest.webmanifest`, `sw.js` (caches only the static shell; never `/api` or uploads; app shows an offline banner and refuses to submit while offline), and icons derived from the unaltered Bonjour logo in `public/assets/`.

## Known limits
* Bank-transfer and Paystack flows need real credentials / a real account to verify end-to-end.
* The rate limiter and in-process caches are per worker.
* Reports export to CSV and PDF; scheduled email delivery of reports is not included.
