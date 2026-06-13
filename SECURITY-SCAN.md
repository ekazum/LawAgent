# LawAgent Security Scan

**Date:** 2026-06-13  **Target:** https://anat-lawagent.duckdns.org (GCE VM `lawagent-poc`, project `lawagent-499215`, zone `me-west1-a`)
**Scope:** static analysis, dependency audit, secrets review, SQL injection, access control, dynamic probing of the live app.
**Methodology:** bandit + pip-audit (backend), npm audit (frontend), full source read of auth/DB/upload layers, git-history secret scan, live HTTP probing (unauth access, injection, headers, ports, path traversal, brute-force timing).

> ⚠️ Keep this file in the **private** repo only — it enumerates weaknesses. No secrets/passwords/hashes are recorded here.

---

## Current operational state (as of writing)

- **App is LIVE and all three MEDIUM fixes are verified end-to-end** (2026-06-13, via the normal automated CI deploy at commit `0303ab4` — no manual steps):
  - Auth required = true; unauth `/api` → 401; wrong password → 401; correct bcrypt login → token; token grants access.
  - Security headers present (HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy, CSP); `Server` banner stripped.
  - Container runs as `appuser` (non-root).
- The root-cause deploy bug is fixed: `deploy.sh` now force-recreates app+caddy every deploy, so secret/env and bind-mounted config changes always land.
- VM still running (billing) — stop with `gcloud compute instances stop lawagent-poc --zone me-west1-a` if idle.

---

## Verified SAFE (with evidence)

| Area | Result | Evidence |
|---|---|---|
| **SQL injection** | None | All queries psycopg-parameterized (`%s`). Bandit's 5 `B608` hits in `db.py` are false positives: interpolated parts are static column constants (`DOCUMENT_COLUMNS`), a whitelist-filtered SET clause (`UPDATABLE_DOCUMENT_FIELDS`), and `_vector_literal` forces every element through `%.8f`. Live probes (`anat' OR '1'='1`, `'; DROP TABLE…`) all returned 401, no 500s. |
| **Secrets in git** | None | Full `git log -p` scan found only `${ANTHROPIC_API_KEY}` env refs + a `your_key` README placeholder. `.env` is gitignored (`.gitignore:138`) and untracked. |
| **Path traversal** | Blocked | `/../etc/passwd`, encoded variants, `/backend/auth.py`, `/.env` → all 404 (FastAPI StaticFiles). |
| **Network exposure** | Minimal | Only 443/22 reachable. Port 8000 and Postgres 5432 are firewalled off (not reachable from internet). |
| **Auth coverage** (when configured) | Good | All `/api` routes 401 without a valid session; tokens HMAC-signed, `hmac.compare_digest`, expiry enforced. Open by design: `/health`, `/api/login`, `/api/auth/status`. |
| **TLS** | Good | Real Let's Encrypt cert via Caddy; HTTP→HTTPS 308 redirect. |

---

## Findings

### HIGH — Weak password + no brute-force protection — **brute-force FIXED; weak password OPEN (user's choice), risk now low**
Originally: short/dictionary-like password, and the 1-second `async` failure delay did **not** throttle parallel attempts (measured 20 logins in 1.5s) → online brute-force feasible.
- **FIXED (commit `a3a9618`, verified live):** `backend/ratelimit.py` adds an atomic in-memory sliding-window limiter on `/api/login` — per-IP 5/5min + global 20/min, keyed off the proxy-appended client IP. A parallel burst is now capped regardless of concurrency (live test: 15 concurrent → 5 reached the check, 10 got 429; once exhausted even the correct password is locked out). Successful login clears the IP counter.
- **Still open (by user decision):** the password value itself is weak. With rate-limiting + bcrypt this is now low-risk for a POC, but the durable fix is a strong password or the Entra ID login. The user chose to keep the current password.
- Note: the limiter is per-process/in-memory (resets on restart, not shared across instances) — fine for the single-container deployment; must move to a shared store if ever scaled horizontally.

### MEDIUM — Missing security headers — **FIXED & VERIFIED LIVE** (commit `0303ab4`)
`deploy/Caddyfile`: HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, a CSP, and `Server` banner stripped. Confirmed present on the live site via the automated deploy.

### MEDIUM — Plaintext password storage — **FIXED & VERIFIED LIVE** (commits `2733279` + `b9ca137` + `0303ab4`)
The `app-users` secret is a **bcrypt hash** (no plaintext). `backend/auth.py` verifies with `bcrypt.checkpw` and uses a dummy-hash compare for unknown users (no username-enumeration timing oracle). The value is passed compose-safe via base64 (`APP_USERS_B64`) because raw `$` was mangled to empty by compose `${VAR}` interpolation. Confirmed end-to-end on the live site: auth required, wrong password → 401, correct bcrypt login → token. **The deploy.sh force-recreate fix (`0303ab4`) is what finally made it land reliably.**

### MEDIUM — Container ran as root — **FIXED & VERIFIED LIVE** (commit `0303ab4`)
`Dockerfile` creates `appuser` (uid 10001) and runs as it; model cache moved to `HF_HOME=/app/models` and chowned. Confirmed `whoami` = `appuser` on the live container; embedding model loads and upload work non-root.

### LOW — torch CVE-2025-3000 — **OPEN**
Flagged by pip-audit; no fixed version published yet. Local embedding runtime only (not network-facing) → low exposure. Track for a patch.

### LOW — No upload size limit (DoS) — **FIXED** (commit `e7819bc`)
Caddy enforces a 40MB request-body ceiling upstream (chat base64 inflates ~33%, so 25MB of attachments ≈ 33MB body). App-level checks return friendly Hebrew 413s: 25MB per KB document (checked via `file.size` before read + `len(data)` backstop), 10MB per chat attachment, 25MB total per message (estimated from base64 length). Verified locally: oversized KB/per-file/total all 413; normal uploads pass.

### LOW — No per-user data isolation — **FIXED (conversations) / shared by design (KB)** (commit `04cc931`)
Conversations now carry an `owner` (logged-in username); list/fetch/delete/chat-resume all scope by owner — a user cannot see or touch another's chats (cross-access → 404). Verified locally with two users (alice/bob): each sees only their own, cross-read and cross-delete both 404. The knowledge base (guidelines/examples/precedents) intentionally stays **shared firm-wide** so all users' answers are grounded in the same legal material (user's choice). No-auth/local dev uses a single `local` owner. Pre-existing owner-less conversations (test data) are now invisible.

### LOW — 2 moderate npm advisories — **FIXED** (commit `2247bda`)
`postcss` and `brace-expansion` bumped via `npm audit fix` (transitive dev deps only). `npm audit` now reports 0 vulnerabilities; frontend build unchanged.

### LOW — Over-privileged VM service account — **FIXED**
Originally the VM ran as the default compute SA, which holds project-wide `roles/editor` — combined with the `cloud-platform` OAuth scope, a VM compromise could edit nearly anything in the project. Replaced with a dedicated SA `lawagent-vm@lawagent-499215.iam.gserviceaccount.com` granted **only** `secretmanager.secretAccessor` on the two secrets (`anthropic-api-key`, `app-users`). The OAuth scope stays `cloud-platform` (Secret Manager has no narrower scope), but IAM now limits the token to reading just those two secrets. Required a VM stop/start (static IP preserved). Verified: a fresh deploy fetched both secrets and auth works under the new SA. Blast radius is now "read 2 secrets the app already holds," not project Editor.

### INFO — CORS defaults to localhost in prod
`CORS_ORIGINS` unset in cloud → defaults to localhost. Harmless because the app is same-origin (backend serves the frontend). Could set explicitly for clarity.

---

## Deployment bug discovered during the pass (KEY UNFINISHED ITEM)

Two related issues; the second is **not yet fully fixed**:

1. **Docker Compose `${VAR}` interpolation mangles bcrypt `$` → empty.** Passing the `$`-laden bcrypt hash through `APP_USERS: ${APP_USERS:-}` produced an **empty** value in the container, which silently set `auth_required() = False` and **left the API wide open**. **Fixed** by base64-encoding the user list: `deploy.sh` sets `APP_USERS_B64=$(… | base64 -w0)`, `docker-compose.yml` passes `APP_USERS_B64`, and `auth.py` decodes it (falls back to plaintext `APP_USERS` for direct/local env). Committed `b9ca137`.

2. **`docker compose up -d --build` does NOT recreate a container when only its env value or a bind-mounted config file changed.** This is why fixes "didn't take" repeatedly:
   - Caddy headers didn't apply → fixed by `up -d --force-recreate caddy` in `deploy.sh`.
   - **The app container has the same problem and is NOT yet force-recreated in `deploy.sh`.** So a changed `app-users` secret (or any env change) won't land unless the app image also changed. This is the remaining gap.
   - **TODO:** make `deploy.sh` force-recreate the app too — change the main `up -d --build "$@"` so app is recreated every deploy (e.g. add `--force-recreate`, accepting a ~3s rolling restart), or document that secret changes require `~/deploy.sh --force-recreate`.

   ⚠️ Caution learned the hard way: running `docker compose up` on the VM **without** the `APP_USERS_B64`/`ANTHROPIC_API_KEY` env vars (i.e. not via `deploy.sh`) recreates the app with empty secrets → disables auth / breaks chat. Always deploy via `~/deploy.sh`.

---

## How to resume (bring it back up, fully hardened)

1. **(Recommended) Patch `deploy.sh`** so the app is force-recreated every deploy:
   - Edit `deploy/deploy.sh` — make the first compose command force-recreate (so secret/env changes always land). Commit + push (CI deploys), or run manually in step 2.
2. **Start the stack** (manual, applies secrets correctly):
   ```
   gcloud compute ssh lawagent-poc --zone me-west1-a --command 'cd ~/lawagent && ~/deploy.sh --force-recreate'
   ```
   (`--force-recreate` is passed through to compose so the app picks up `APP_USERS_B64`.)
3. **Verify** (all must hold):
   - `GET /api/auth/status` → `{"required": true}`
   - `GET /api/conversations` with no token → **401**
   - `POST /api/login` correct creds → token; wrong creds → 401
   - `GET /` response headers include HSTS, X-Frame-Options, CSP; no `Server` header
   - `docker exec lawagent-app whoami` → `appuser`
4. **(Optional, addresses HIGH)** Set a strong password: generate a new bcrypt hash, `gcloud secrets versions add app-users --data-file=-` with `username:hash`, then re-deploy (force-recreate). Changing the user list also rotates the session signing key (logs everyone out).

## Recommended next actions (priority order)
1. Patch `deploy.sh` app force-recreate (closes the "fixes don't apply" trap). **Required for reliable deploys.**
2. Strong password + brute-force lockout, or Entra ID login (the only HIGH finding).
3. `npm audit fix`; add upload size limit.
4. Per-user data isolation before onboarding more than the trusted few.

## Reference
- Key files: `backend/auth.py` (login/tokens), `backend/db.py` (queries), `backend/main.py` (middleware/upload), `deploy/Caddyfile` (headers), `deploy/deploy.sh` (deploy), `Dockerfile` (non-root), `docker-compose.yml`.
- Secrets in GCP Secret Manager: `anthropic-api-key`, `app-users` (bcrypt `user:hash` lines).
- Scanners: `python -m bandit -r backend -ll`, `pip-audit -r backend/requirements.txt`, `npm --prefix frontend audit`.
