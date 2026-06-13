# LawAgent Security Scan

**Date:** 2026-06-13 (kept updated as items are resolved)
**Target:** https://anat-lawagent.duckdns.org (GCE VM `lawagent-poc`, project `lawagent-499215`, zone `me-west1-a`)
**Scope:** static analysis, dependency audit, secrets review, SQL injection, access control, dynamic probing of the live app.
**Methodology:** bandit + pip-audit (backend), npm audit (frontend), full source read of auth/DB/upload layers, git-history secret scan, live HTTP probing.

> ⚠️ Keep this file in the **private** repo only. No secrets/passwords/hashes are recorded here.
> Resolved findings are removed from this document; their fixes are in git history.

---

## Status

App is **live and hardened** at the target above. The pass closed every MEDIUM and LOW finding and the brute-force half of the HIGH finding. Only the items under **Open items** remain.

---

## Verified SAFE (with evidence)

| Area | Result | Evidence |
|---|---|---|
| **SQL injection** | None | All queries are psycopg-parameterized (`%s`); SQL lives in `queries.py` built only from literals + whitelisted identifiers. Live probes (`anat' OR '1'='1`, `'; DROP TABLE…`) returned 401, no 500s. |
| **Secrets in git** | None | `git log -p` scan found only `${ANTHROPIC_API_KEY}` env refs + a README placeholder. `.env` is gitignored and untracked. |
| **Path traversal** | Blocked | `/../etc/passwd`, encoded variants, `/.env` → 404 (FastAPI StaticFiles). |
| **Network exposure** | Minimal | Only 443/22 reachable. Port 8000 and Postgres 5432 are firewalled off. |
| **Auth coverage** | Good | All `/api` routes 401 without a valid session; tokens HMAC-signed, timing-safe compare, expiry enforced. Open by design: `/health`, `/api/login`, `/api/auth/status`. |
| **TLS** | Good | Real Let's Encrypt cert via Caddy; HTTP→HTTPS 308 redirect. |

---

## Open items

### HIGH (residual) — Weak password value — OPEN (user's choice)
The brute-force exposure is fixed (per-IP 5/5min + global 20/min rate limiting in `backend/ratelimit.py`, plus bcrypt hashing). What remains is that the chosen passwords are short dictionary words. Low-risk for the POC behind the rate limiter, but the durable fix is strong passwords or the Microsoft Entra ID login. The user chose to keep the current passwords.

### LOW — torch CVE-2025-3000 — OPEN
Flagged by pip-audit; no upstream patch published yet. Local embedding runtime only (not network-facing) → low exposure. Bump `torch` when a fixed version ships.

### INFO — CORS defaults to localhost in prod
`CORS_ORIGINS` is unset in the cloud, so it defaults to localhost. Harmless because the app is same-origin (the backend serves the frontend); could be set explicitly for clarity.

---

## Reference
- Key files: `backend/auth.py` (Authenticator/tokens), `backend/db.py` + `backend/queries.py` (Database/SQL), `backend/app.py` (routes/middleware), `backend/dependencies.py`, `deploy/Caddyfile` (security headers), `deploy/deploy.sh` (deploy), `Dockerfile`, `docker-compose.yml`.
- Secrets in GCP Secret Manager: `anthropic-api-key`, `app-users` (bcrypt `user:hash` lines).
- Re-run scanners: `python -m bandit -r backend -ll`, `pip-audit -r backend/requirements.txt`, `npm --prefix frontend audit`.
