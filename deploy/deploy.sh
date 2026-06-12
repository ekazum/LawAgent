#!/bin/sh
# Runs ON the VM. Extracts the uploaded tarball and (re)starts the stack.
# Secrets come from GCP Secret Manager via the VM's service account.
set -e
cd "$HOME"
mkdir -p lawagent
[ -f lawagent.tar.gz ] && tar xzf lawagent.tar.gz -C lawagent
cd lawagent
# app-users holds bcrypt hashes ('$'-laden); base64 it so compose's ${VAR}
# interpolation passes it through verbatim (raw '$' would be mangled to empty).
sudo ANTHROPIC_API_KEY="$(gcloud secrets versions access latest --secret anthropic-api-key)" \
     APP_USERS_B64="$(gcloud secrets versions access latest --secret app-users | base64 -w0)" \
     docker compose --profile cloud up -d --build "$@"

# compose won't recreate caddy when only the bind-mounted Caddyfile content
# changed, and `caddy reload` proved unreliable here, so force-recreate it.
# The Let's Encrypt cert lives in the caddy_data volume, so this is cheap
# (no re-issuance) — just a ~1s blip.
sudo docker compose --profile cloud up -d --force-recreate caddy
