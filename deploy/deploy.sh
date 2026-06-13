#!/bin/sh
# Runs ON the VM. Extracts the uploaded tarball and (re)starts the stack.
# Secrets come from GCP Secret Manager via the VM's service account.
set -e
cd "$HOME"
mkdir -p lawagent
[ -f lawagent.tar.gz ] && tar xzf lawagent.tar.gz -C lawagent
cd lawagent
# Force-recreate app+caddy on every deploy so env/secret and bind-mounted
# config changes always land. Plain `up -d` skips recreation when only an
# env value or a mounted file changed, which previously caused fixes (the
# auth secret, the Caddy headers) to silently not apply. db is started as a
# dependency but not recreated (its pgdata volume persists either way).
#
# app-users holds bcrypt hashes ('$'-laden); base64 it so compose's ${VAR}
# interpolation passes it through verbatim (raw '$' would be mangled to empty).
# The Let's Encrypt cert lives in the caddy_data volume, so recreating caddy
# is cheap (no re-issuance).
sudo ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret anthropic-api-key)" \
     APP_USERS_B64="$(gcloud secrets versions access latest --secret app-users | base64 -w0)" \
     docker compose --profile cloud up -d --build --force-recreate app caddy
